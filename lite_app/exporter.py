"""Excel 导出系统：新建工作簿和固定模板映射。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import column_index_from_string

from .config import PROJECT_ROOT, load_export_config
from .storage import JobStorage

logger = logging.getLogger(__name__)

MAX_AUTO_WIDTH = 50


class ExportError(Exception):
    """导出错误。"""
    pass


def export_job(job_id: str, storage: JobStorage | None = None) -> str:
    """
    导出任务结果为 Excel。

    返回输出文件名。
    """
    if storage is None:
        storage = JobStorage()

    job = storage.get_job(job_id)
    result = storage.load_result(job_id)
    if result is None:
        raise ExportError("识别结果不存在，请先完成识别。")

    export_config = load_export_config()
    excel_cfg = export_config.get("excel", {})

    template_path_str = excel_cfg.get("template_path", "")
    keep_vba = excel_cfg.get("keep_vba", False)
    output_name = excel_cfg.get("output_name", "recognized-{job_id}.xlsx")
    output_name = output_name.replace("{job_id}", job_id)

    job_dir = storage.get_job_dir(job_id)
    output_path = job_dir / output_name

    # 加载或创建工作簿
    if template_path_str:
        template_path = Path(template_path_str)
        if not template_path.is_absolute():
            template_path = PROJECT_ROOT / template_path
        if not template_path.exists():
            raise ExportError(f"Excel 模板不存在: {template_path}")
        wb = load_workbook(str(template_path), keep_vba=keep_vba)
        is_template = True
    else:
        wb = Workbook()
        # 删除默认 Sheet
        if "Sheet" in wb.sheetnames:
            del wb["Sheet"]
        is_template = False

    # 写入单元格映射
    cells = excel_cfg.get("cells", [])
    _write_cells(wb, cells, result)

    # 写入表格映射
    tables = excel_cfg.get("tables", [])
    for table_cfg in tables:
        _write_table(wb, table_cfg, result, is_template)

    # 保存
    wb.save(str(output_path))
    logger.info("导出完成: %s", output_path)

    # 更新任务状态
    job["export_file"] = output_name
    job["status"] = "EXPORTED"
    job["status_message"] = f"已导出: {output_name}"
    storage.save_job(job)

    return output_name


def _get_sheet(wb: Workbook, sheet_name: str) -> Any:
    """获取或创建工作表。"""
    if sheet_name in wb.sheetnames:
        return wb[sheet_name]
    return wb.create_sheet(title=sheet_name)


def _resolve_value(
    expr: str,
    item: dict[str, Any],
    root: dict[str, Any],
    parent: dict[str, Any] | None,
    index: int,
    parent_index: int,
) -> Any:
    """解析表达式值。"""
    if expr.startswith("literal:"):
        return expr[len("literal:"):]

    if expr == "$index":
        return index

    if expr == "$parent_index":
        return parent_index

    if expr.startswith("$root."):
        field = expr[len("$root."):]
        return _get_field(root, field)

    if expr.startswith("$parent."):
        if parent is None:
            return ""
        field = expr[len("$parent."):]
        return _get_field(parent, field)

    # 普通字段
    return _get_field(item, expr)


def _get_field(obj: dict[str, Any], field: str) -> Any:
    """获取字段值，列表/对象转为 JSON 字符串。"""
    value = obj.get(field, "")
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _write_cells(
    wb: Workbook, cells: list[dict[str, Any]], result: dict[str, Any]
) -> None:
    """写入单元格映射。"""
    for cell_cfg in cells:
        sheet_name = cell_cfg["sheet"]
        cell_ref = cell_cfg["cell"]
        expr = cell_cfg["value"]
        ws = _get_sheet(wb, sheet_name)
        value = _resolve_value(expr, {}, result, None, 0, 0)
        ws[cell_ref] = value


def _write_table(
    wb: Workbook,
    table_cfg: dict[str, Any],
    result: dict[str, Any],
    is_template: bool,
) -> None:
    """写入表格映射。"""
    sheet_name = table_cfg["sheet"]
    source_key = table_cfg.get("source", "records")
    expand_key = table_cfg.get("expand", "")
    start_row = table_cfg.get("start_row", 1)
    include_header = table_cfg.get("include_header", True)
    auto_width = table_cfg.get("auto_width", False)
    columns = table_cfg.get("columns", [])

    ws = _get_sheet(wb, sheet_name)
    records = result.get(source_key, [])

    current_row = start_row

    # 写表头
    if include_header:
        for col_cfg in columns:
            col_letter = col_cfg["column"]
            header = col_cfg.get("header", "")
            col_idx = column_index_from_string(col_letter)
            cell = ws.cell(row=current_row, column=col_idx, value=header)
            if not is_template:
                cell.font = Font(bold=True)
                cell.fill = PatternFill(
                    start_color="D9E1F2", end_color="D9E1F2", fill_type="solid"
                )
        current_row += 1

    # 写数据
    if expand_key:
        # 展开子数组
        for parent_idx, record in enumerate(records, 1):
            sub_items = record.get(expand_key, [])
            for item_idx, item in enumerate(sub_items, 1):
                for col_cfg in columns:
                    col_letter = col_cfg["column"]
                    expr = col_cfg["value"]
                    col_idx = column_index_from_string(col_letter)
                    value = _resolve_value(
                        expr, item, result, record, item_idx, parent_idx
                    )
                    ws.cell(row=current_row, column=col_idx, value=value)
                current_row += 1
    else:
        # 直接写记录
        for item_idx, record in enumerate(records, 1):
            for col_cfg in columns:
                col_letter = col_cfg["column"]
                expr = col_cfg["value"]
                col_idx = column_index_from_string(col_letter)
                value = _resolve_value(
                    expr, record, result, None, item_idx, 0
                )
                ws.cell(row=current_row, column=col_idx, value=value)
            current_row += 1

    # 自动列宽
    if auto_width:
        _auto_column_width(ws, columns)


def _auto_column_width(ws: Any, columns: list[dict[str, Any]]) -> None:
    """自动调整列宽，限制最大宽度。"""
    for col_cfg in columns:
        col_letter = col_cfg["column"]
        max_len = 0
        for row in ws.iter_rows(
            min_col=column_index_from_string(col_letter),
            max_col=column_index_from_string(col_letter),
        ):
            for cell in row:
                if cell.value is not None:
                    cell_len = len(str(cell.value))
                    max_len = max(max_len, cell_len)
        # 中文字符占约2个宽度
        width = min(max_len + 2, MAX_AUTO_WIDTH)
        ws.column_dimensions[col_letter].width = max(width, 8)
