"""Excel 导出模块测试。"""

import json
import pytest
from pathlib import Path

from openpyxl import Workbook, load_workbook

from lite_app.exporter import ExportError, export_job, _resolve_value


SAMPLE_RESULT = {
    "page_heading": "测试标题",
    "records": [
        {
            "source_image_indexes": [1],
            "record_date": "24.7.10",
            "title": "配方A",
            "materials": [
                {"name": "PA66", "amount": "60", "unit": "kg", "confidence": 0.95},
                {"name": "GF30", "amount": "30", "unit": "", "confidence": 0.90},
            ],
            "process_parameters": [
                {"name": "转速", "value": "50", "unit": "Hz", "confidence": 0.88},
            ],
            "notes": "备注内容",
            "confidence": 0.92,
            "warnings": ["警告1"],
        }
    ],
    "warnings": ["全局警告"],
}


class TestResolveValue:
    def test_literal(self):
        assert _resolve_value("literal:固定文字", {}, {}, None, 0, 0) == "固定文字"

    def test_index(self):
        assert _resolve_value("$index", {}, {}, None, 3, 0) == 3

    def test_parent_index(self):
        assert _resolve_value("$parent_index", {}, {}, None, 0, 2) == 2

    def test_root_field(self):
        root = {"page_heading": "标题"}
        assert _resolve_value("$root.page_heading", {}, root, None, 0, 0) == "标题"

    def test_parent_field(self):
        parent = {"title": "配方X"}
        assert _resolve_value("$parent.title", {}, {}, parent, 0, 0) == "配方X"

    def test_normal_field(self):
        item = {"name": "PA66", "amount": "60"}
        assert _resolve_value("name", item, {}, None, 0, 0) == "PA66"

    def test_list_field_as_json(self):
        item = {"warnings": ["a", "b"]}
        result = _resolve_value("warnings", item, {}, None, 0, 0)
        assert result == '["a", "b"]'


class TestExportJob:
    @pytest.fixture
    def job_with_result(self, storage):
        """创建带有识别结果的任务。"""
        job = storage.create_job()
        storage.save_result(job["id"], SAMPLE_RESULT)
        job["status"] = "READY"
        storage.save_job(job)
        return job

    def test_export_creates_file(self, job_with_result, storage):
        filename = export_job(job_with_result["id"], storage)
        assert filename.endswith(".xlsx")
        job_dir = storage.get_job_dir(job_with_result["id"])
        assert (job_dir / filename).exists()

    def test_export_creates_three_sheets(self, job_with_result, storage):
        filename = export_job(job_with_result["id"], storage)
        job_dir = storage.get_job_dir(job_with_result["id"])
        wb = load_workbook(str(job_dir / filename))
        assert "记录汇总" in wb.sheetnames
        assert "配方明细" in wb.sheetnames
        assert "工艺参数" in wb.sheetnames

    def test_export_cell_mapping(self, job_with_result, storage):
        filename = export_job(job_with_result["id"], storage)
        job_dir = storage.get_job_dir(job_with_result["id"])
        wb = load_workbook(str(job_dir / filename))
        ws = wb["记录汇总"]
        assert ws["B1"].value == "测试标题"

    def test_export_records_table(self, job_with_result, storage):
        filename = export_job(job_with_result["id"], storage)
        job_dir = storage.get_job_dir(job_with_result["id"])
        wb = load_workbook(str(job_dir / filename))
        ws = wb["记录汇总"]
        # 表头在第3行
        assert ws.cell(row=3, column=1).value == "序号"
        # 数据在第4行
        assert ws.cell(row=4, column=1).value == 1
        assert ws.cell(row=4, column=3).value == "24.7.10"
        assert ws.cell(row=4, column=4).value == "配方A"

    def test_export_materials_expand(self, job_with_result, storage):
        filename = export_job(job_with_result["id"], storage)
        job_dir = storage.get_job_dir(job_with_result["id"])
        wb = load_workbook(str(job_dir / filename))
        ws = wb["配方明细"]
        # 表头
        assert ws.cell(row=1, column=5).value == "原料名称"
        # 数据
        assert ws.cell(row=2, column=5).value == "PA66"
        assert ws.cell(row=2, column=6).value == "60"
        assert ws.cell(row=3, column=5).value == "GF30"
        # 父记录字段
        assert ws.cell(row=2, column=1).value == 1  # parent_index
        assert ws.cell(row=2, column=2).value == "24.7.10"  # parent.record_date

    def test_export_process_expand(self, job_with_result, storage):
        filename = export_job(job_with_result["id"], storage)
        job_dir = storage.get_job_dir(job_with_result["id"])
        wb = load_workbook(str(job_dir / filename))
        ws = wb["工艺参数"]
        assert ws.cell(row=2, column=5).value == "转速"
        assert ws.cell(row=2, column=6).value == "50"
        assert ws.cell(row=2, column=7).value == "Hz"

    def test_export_updates_job_status(self, job_with_result, storage):
        export_job(job_with_result["id"], storage)
        job = storage.get_job(job_with_result["id"])
        assert job["status"] == "EXPORTED"
        assert job["export_file"] is not None

    def test_export_no_result_raises(self, storage):
        job = storage.create_job()
        with pytest.raises(ExportError, match="不存在"):
            export_job(job["id"], storage)

    def test_export_with_template(self, storage, tmp_path, monkeypatch):
        """使用已有模板导出：验证原内容保留、新数据写入、源模板不被修改。"""
        # 创建带有原内容和额外 Sheet 的模板
        template = tmp_path / "template.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.title = "记录汇总"
        ws["A1"] = "原有标题"
        ws["Z1"] = "额外内容"
        extra_ws = wb.create_sheet("自定义Sheet")
        extra_ws["A1"] = "自定义数据"
        wb.create_sheet("配方明细")
        wb.create_sheet("工艺参数")
        wb.save(str(template))

        # 记录模板原始大小
        original_size = template.stat().st_size

        # 创建任务
        job = storage.create_job()
        storage.save_result(job["id"], SAMPLE_RESULT)
        job["status"] = "READY"
        storage.save_job(job)

        # monkeypatch 导出配置指向模板
        import lite_app.exporter as exp_module

        def mock_load_export():
            return {
                "excel": {
                    "template_path": str(template),
                    "keep_vba": False,
                    "output_name": "out-{job_id}.xlsx",
                    "cells": [
                        {"sheet": "记录汇总", "cell": "B1", "value": "$root.page_heading"}
                    ],
                    "tables": [
                        {
                            "name": "records",
                            "sheet": "记录汇总",
                            "source": "records",
                            "start_row": 3,
                            "include_header": True,
                            "auto_width": False,
                            "columns": [
                                {"column": "A", "header": "序号", "value": "$index"},
                                {"column": "B", "header": "日期", "value": "record_date"},
                            ],
                        }
                    ],
                }
            }

        monkeypatch.setattr(exp_module, "load_export_config", mock_load_export)

        # 执行导出
        filename = export_job(job["id"], storage)
        job_dir = storage.get_job_dir(job["id"])
        output_path = job_dir / filename
        assert output_path.exists()

        # 验证输出文件
        out_wb = load_workbook(str(output_path))
        out_ws = out_wb["记录汇总"]
        # 原内容保留
        assert out_ws["A1"].value == "原有标题"
        assert out_ws["Z1"].value == "额外内容"
        # 新写入的数据
        assert out_ws["B1"].value == "测试标题"
        assert out_ws.cell(row=3, column=1).value == "序号"
        assert out_ws.cell(row=4, column=1).value == 1
        assert out_ws.cell(row=4, column=2).value == "24.7.10"
        # 额外 Sheet 保留
        assert "自定义Sheet" in out_wb.sheetnames
        assert out_wb["自定义Sheet"]["A1"].value == "自定义数据"

        # 源模板未被修改
        assert template.stat().st_size == original_size

    def test_export_template_not_exists_raises(self, storage, monkeypatch):
        """模板不存在时报错。"""
        job = storage.create_job()
        storage.save_result(job["id"], SAMPLE_RESULT)
        job["status"] = "READY"
        storage.save_job(job)

        # 通过 monkeypatch 修改配置
        import lite_app.exporter as exp_module

        def mock_load_export():
            return {
                "excel": {
                    "template_path": "/nonexistent/path/template.xlsx",
                    "keep_vba": False,
                    "output_name": "out-{job_id}.xlsx",
                    "cells": [],
                    "tables": [],
                }
            }

        monkeypatch.setattr(exp_module, "load_export_config", mock_load_export)
        with pytest.raises(ExportError, match="不存在"):
            export_job(job["id"], storage)

    def test_output_in_job_dir(self, job_with_result, storage):
        filename = export_job(job_with_result["id"], storage)
        job_dir = storage.get_job_dir(job_with_result["id"])
        output_path = job_dir / filename
        assert output_path.exists()
        assert output_path.parent == job_dir
