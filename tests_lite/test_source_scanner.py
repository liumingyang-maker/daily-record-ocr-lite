from pathlib import Path

import pytest

from lite_app.knowledge.source_scanner import classify_source, scan_sources


def test_macos_metadata_is_always_excluded() -> None:
    decision = classify_source(Path("__MACOSX/联创/._联创.xlsx"))

    assert decision.action == "exclude"
    assert decision.reason == "MACOS_METADATA"


def test_formula_workbook_is_a_candidate_with_customer_hint() -> None:
    decision = classify_source(Path("博厚/博厚配方.xlsx"))

    assert decision.action == "candidate"
    assert decision.reason == "FORMULA_WORKBOOK"
    assert decision.customer_hint == "博厚"


def test_non_formula_business_documents_are_excluded() -> None:
    assert classify_source(Path("1报告合集/检测报告.xlsx")).reason == (
        "NON_FORMULA_DOCUMENT"
    )
    assert classify_source(Path("其他/购销合同.xlsx")).reason == (
        "NON_FORMULA_DOCUMENT"
    )
    assert classify_source(Path("客户/产品标签.xlsx")).reason == (
        "NON_FORMULA_DOCUMENT"
    )


@pytest.mark.parametrize(
    "path",
    [
        "客户/年度报价.xlsx",
        "客户/SGS检测报告.xlsx",
        "客户/产品成分表.xlsx",
        "客户/原料物性.xlsx",
        "1报告合集/任意文件.xlsx",
    ],
)
def test_each_known_non_formula_category_is_rejected(path: str) -> None:
    decision = classify_source(Path(path))

    assert decision.action == "exclude"
    assert decision.reason == "NON_FORMULA_DOCUMENT"


def test_non_excel_files_are_excluded() -> None:
    decision = classify_source(Path("联创/现场照片.jpg"))

    assert decision.action == "exclude"
    assert decision.reason == "UNSUPPORTED_FORMAT"


def test_scan_sources_is_sorted_and_does_not_follow_outside_paths(
    tmp_path: Path,
) -> None:
    (tmp_path / "联创").mkdir()
    (tmp_path / "联创" / "联创.xlsx").touch()
    (tmp_path / "__MACOSX").mkdir()
    (tmp_path / "__MACOSX" / "._联创.xlsx").touch()
    (tmp_path / "说明.txt").touch()

    decisions = scan_sources(tmp_path)

    assert [item.path.as_posix() for item in decisions] == [
        "__MACOSX/._联创.xlsx",
        "联创/联创.xlsx",
        "说明.txt",
    ]
    assert sum(item.action == "candidate" for item in decisions) == 1
