from __future__ import annotations

import json

from lite_app.review_view import build_review_view
from tests_lite.review_fixtures import make_review_final


def _job() -> dict:
    return {
        "id": "job-review",
        "status": "REVIEW_REQUIRED",
        "images": [{"source": "source/a.jpg"}],
    }


def test_review_view_groups_by_customer_product_and_prioritizes_issues():
    view = build_review_view(_job(), make_review_final("job-review"), confirmed={})

    group = view["groups"][0]
    formula = group["formulas"][0]
    assert group["customer"] == "联创"
    assert group["product"] == "G30A"
    assert view["summary"]["needs_confirmation"] == 1
    assert formula["needs_confirmation"] is True
    assert formula["evidence"]["image_url"].endswith("source/a.jpg")
    assert formula["evidence"]["rect"] == [0.05, 0.18, 0.95, 0.55]
    assert "field_id" not in formula["materials"][0]
    assert formula["materials"][0]["amount"]["needs_confirmation"] is True
    assert formula["date_pending"] is True
    assert formula["blocking_message"] == "待确认：联创 / G30A / 配方1 材料数量需要确认"


def test_review_view_uses_business_labels_and_separates_technical_metadata():
    view = build_review_view(_job(), make_review_final("job-review"), confirmed={})
    formula = view["groups"][0]["formulas"][0]

    assert formula["labels"] == {
        "date": "日期",
        "materials": "材料与数量",
        "process": "工艺",
        "notes": "备注",
    }
    visible = json.dumps(view["groups"], ensure_ascii=False)
    assert "field_id" not in visible
    assert "candidates" not in visible
    assert "OCR" not in visible
    assert "VLM" not in visible
    assert "BBox" not in visible
    assert view["advanced"]["job_id"] == "job-review"


def test_review_view_orders_issue_formulas_before_confirmed_formulas():
    final = make_review_final("job-review")
    section = final["pages"][0]["product_sections"][0]
    resolved = json.loads(json.dumps(section["formulas"][0]))
    resolved["formula_id"] = "job-review__page_001__formula_000"
    resolved["formula_no"] = "配方0"
    resolved["record_date"]["value"] = "2026-07-01"
    resolved["record_date"]["status"] = "AUTO_ACCEPT"
    resolved["materials"][0]["amount"]["status"] = "AUTO_ACCEPT"
    section["formulas"].insert(0, resolved)

    view = build_review_view(_job(), final, confirmed={resolved["formula_id"]: True})

    formulas = view["groups"][0]["formulas"]
    assert [item["formula_no"] for item in formulas] == ["配方1", "配方0"]
    assert formulas[0]["collapsed"] is False
    assert formulas[1]["collapsed"] is True


def test_review_view_preserves_date_text_and_exposes_internal_sort_state():
    final = make_review_final("job-review")
    formula = final["pages"][0]["product_sections"][0]["formulas"][0]
    formula["record_date"]["value"] = "24.7.19"
    formula["record_date"]["status"] = "AUTO_ACCEPT"

    view = build_review_view(_job(), final, confirmed={})
    date = view["groups"][0]["formulas"][0]["date"]

    assert date["value"] == "24.7.19"
    assert date["sort_value"] == "2024-07-19"
    assert date["parse_status"] == "KNOWN"
