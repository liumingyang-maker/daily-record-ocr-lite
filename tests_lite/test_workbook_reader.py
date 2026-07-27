from datetime import datetime
from pathlib import Path

import openpyxl
import xlwt

from lite_app.knowledge.workbook_reader import read_workbook


def _write_xlsx(path: Path) -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "G30A"
    sheet["A1"] = "G30A"
    sheet["C1"] = datetime(2024, 7, 12)
    sheet["A2"] = "配方"
    sheet["B2"] = "PA6"
    sheet["C2"] = "玻纤"
    sheet["B3"] = "55"
    sheet["C3"] = "35-36"
    workbook.save(path)


def _write_xls(path: Path) -> None:
    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("G30A")
    sheet.write(0, 0, "G30A")
    sheet.write(1, 0, "配方")
    sheet.write(1, 1, "PA6")
    sheet.write(2, 1, "55")
    workbook.save(str(path))


def test_reads_xlsx_cells_and_date_without_mutating_source(tmp_path: Path) -> None:
    path = tmp_path / "联创.xlsx"
    _write_xlsx(path)
    before = path.read_bytes()

    workbook = read_workbook(path)

    assert [sheet.name for sheet in workbook.sheets] == ["G30A"]
    sheet = workbook.sheets[0]
    assert sheet.value_at(2, 1) == "配方"
    assert sheet.value_at(2, 2) == "PA6"
    assert sheet.cell_at(1, 3).is_date is True
    assert sheet.value_at(1, 3) == "2024-07-12"
    assert path.read_bytes() == before


def test_reads_legacy_xls_into_the_same_cell_contract(tmp_path: Path) -> None:
    path = tmp_path / "联创.xls"
    _write_xls(path)

    workbook = read_workbook(path)

    assert workbook.format == "xls"
    assert workbook.sheets[0].value_at(2, 1) == "配方"
    assert workbook.sheets[0].value_at(2, 2) == "PA6"
    assert workbook.sheets[0].value_at(3, 2) == "55"


def test_rejects_unsupported_workbook_format(tmp_path: Path) -> None:
    path = tmp_path / "配方.csv"
    path.write_text("配方,PA6", encoding="utf-8")

    try:
        read_workbook(path)
    except ValueError as exc:
        assert "不支持" in str(exc)
    else:
        raise AssertionError("CSV must not be accepted by the workbook reader")
