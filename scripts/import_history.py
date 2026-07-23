"""历史数据导入脚本：从 Excel/CSV 导入物料和配方到知识库。"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lite_app.config import PROJECT_ROOT
from lite_app.knowledge.database import KnowledgeDB


def import_csv(db: KnowledgeDB, csv_path: Path) -> int:
    """从 CSV 导入物料。"""
    count = 0
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("物料名称") or row.get("name") or row.get("material") or "").strip()
            if not name:
                continue
            unit = (row.get("单位") or row.get("unit") or "").strip()
            category = (row.get("分类") or row.get("category") or "").strip()
            mid = db.add_material(name, category, unit)

            alias_str = (row.get("别名") or row.get("aliases") or "").strip()
            if alias_str:
                for alias in alias_str.replace("；", ";").split(";"):
                    if alias.strip():
                        db.add_alias(mid, alias.strip(), alias_type="import", source="csv")
            count += 1
    return count


def import_xlsx(db: KnowledgeDB, xlsx_path: Path) -> int:
    """从 Excel 导入物料。"""
    from openpyxl import load_workbook

    wb = load_workbook(str(xlsx_path), read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if len(rows) < 2:
        print("文件行数不足。")
        return 0

    headers = [str(h or "").strip() for h in rows[0]]
    name_col = None
    unit_col = None
    category_col = None
    alias_col = None

    for i, h in enumerate(headers):
        hl = h.lower()
        if "物料" in h or "名称" in h or hl == "name" or hl == "material":
            name_col = i
        elif "单位" in h or hl == "unit":
            unit_col = i
        elif "分类" in h or hl == "category":
            category_col = i
        elif "别名" in h or hl == "aliases":
            alias_col = i

    if name_col is None:
        name_col = 0

    count = 0
    for row in rows[1:]:
        if not row or len(row) <= name_col:
            continue
        name = str(row[name_col] or "").strip()
        if not name:
            continue
        unit = str(row[unit_col] or "").strip() if unit_col is not None and len(row) > unit_col else ""
        category = str(row[category_col] or "").strip() if category_col is not None and len(row) > category_col else ""
        mid = db.add_material(name, category, unit)

        if alias_col is not None and len(row) > alias_col:
            alias_str = str(row[alias_col] or "").strip()
            if alias_str:
                for alias in alias_str.replace("；", ";").split(";"):
                    if alias.strip():
                        db.add_alias(mid, alias.strip(), alias_type="import", source="xlsx")
        count += 1

    wb.close()
    return count


def main():
    parser = argparse.ArgumentParser(description="导入历史物料数据到知识库")
    parser.add_argument("file", help="要导入的文件路径 (.xlsx 或 .csv)")
    parser.add_argument("--db", default=None, help="知识库路径（默认 data/knowledge.sqlite3）")
    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"文件不存在: {file_path}")
        sys.exit(1)

    db_path = Path(args.db) if args.db else PROJECT_ROOT / "data" / "knowledge.sqlite3"
    db = KnowledgeDB(db_path)
    db.initialize()

    ext = file_path.suffix.lower()
    if ext == ".csv":
        count = import_csv(db, file_path)
    elif ext == ".xlsx":
        count = import_xlsx(db, file_path)
    else:
        print(f"不支持的文件类型: {ext}。允许: .xlsx, .csv")
        sys.exit(1)

    print(f"成功导入 {count} 条物料记录到 {db_path}")
    db.close()


if __name__ == "__main__":
    main()
