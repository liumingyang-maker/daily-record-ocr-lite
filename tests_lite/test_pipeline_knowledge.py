from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from lite_app.final_result import project_final_result
from lite_app.knowledge.database import KnowledgeDB
from lite_app.ocr.base import OCRPage, OCRToken
from lite_app.pipeline_v2 import (
    _apply_knowledge_correction,
    _build_fusion_result,
    _build_knowledge_prompt,
    _history_candidates,
    _knowledge_assist_enabled,
)


def _seed_term(
    db_path: Path,
    *,
    term_type: str,
    value: str,
    customer: str = "",
    product: str = "",
) -> None:
    database = KnowledgeDB(db_path)
    database.initialize()
    connection = database._get_conn()
    now = datetime.now(UTC).isoformat()
    term_id = connection.execute(
        """
        INSERT INTO lexicon_terms (
            term_type, standard_value, normalized_value, source_quality,
            occurrence_count, created_at, updated_at
        ) VALUES (?, ?, lower(?), 'confirmed', 3, ?, ?)
        """,
        (term_type, value, value, now, now),
    ).lastrowid
    connection.execute(
        """
        INSERT INTO lexicon_context_stats (
            term_id, customer_context, product_context, occurrence_count
        ) VALUES (?, ?, ?, 3)
        """,
        (term_id, customer, product),
    )
    connection.commit()
    database.close()


def _ocr_page(text: str) -> OCRPage:
    token = OCRToken(
        id="p1_t001",
        text=text,
        confidence=0.72,
        polygon=[[10, 10], [90, 10], [90, 30], [10, 30]],
        bbox=[10, 10, 90, 30],
        center_x=50,
        center_y=20,
    )
    return OCRPage(
        image_index=1,
        width=100,
        height=100,
        tokens=[token],
        average_confidence=0.72,
        provider="paddleocr_v6",
        model="PP-OCRv6_medium",
        elapsed_ms=1,
    )


def _structured(material: str = "PA66 GF3O") -> dict:
    return {
        "pages": [
            {
                "source_image_index": 1,
                "company": {"standard_value": "联创"},
                "product_sections": [
                    {
                        "product_or_series": {"value": "G30A"},
                        "formulas": [
                            {
                                "formula_id": "formula_001",
                                "materials": [
                                    {
                                        "material_id": "material_001",
                                        "name": {
                                            "value": material,
                                            "confidence": 0.91,
                                            "evidence_token_ids": ["p1_t001"],
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }


def test_knowledge_references_enter_prompt_as_non_numeric_hints(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "knowledge.sqlite3"
    _seed_term(
        db_path,
        term_type="material",
        value="PA66 GF30",
        customer="联创",
        product="G30A",
    )

    prompt = _build_knowledge_prompt([_ocr_page("PA66 GF3O")], db_path)

    assert prompt["references"][0]["raw_text"] == "PA66 GF3O"
    assert prompt["references"][0]["candidate"] == "PA66 GF30"
    assert prompt["references"][0]["term_type"] == "material"
    assert prompt["policy"]["never_override"] == [
        "amount",
        "date",
        "formula_no",
        "identifier",
        "unit",
    ]


def test_knowledge_assistance_can_be_disabled_for_ab_gate(monkeypatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_ASSIST_ENABLED", "false")

    assert _knowledge_assist_enabled() is False


def test_post_vision_retrieval_is_typed_and_context_scoped(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "knowledge.sqlite3"
    _seed_term(
        db_path,
        term_type="material",
        value="PA66 GF30",
        customer="联创",
        product="G30A",
    )
    _seed_term(
        db_path,
        term_type="material",
        value="PA66 GF3B",
        customer="其他客户",
        product="G30A",
    )

    matches = _history_candidates(_structured(), db_path)

    candidate = matches["formula_001__material_001__name"][0]
    assert candidate["value"] == "PA66 GF30"
    assert candidate["term_type"] == "material"
    assert candidate["context_aligned"] is True
    assert "product_context" in candidate["reasons"]


def test_unique_contextual_history_correction_writes_reversible_trace() -> None:
    result = {
        "final_value": "PA66 GF3O",
        "final_source": "vlm",
        "final_confidence": 0.91,
        "status": "AUTO_ACCEPT",
        "reasons": [],
        "candidates": [
            {
                "value": "PA66 GF3O",
                "source": "vlm",
                "confidence": 0.91,
                "evidence": ["p1_t001"],
            }
        ],
    }
    history = [
        {
            "value": "PA66 GF30",
            "term_type": "material",
            "score": 0.97,
            "context_aligned": True,
            "reasons": ["fuzzy", "product_context"],
        },
        {
            "value": "PA66 GF3B",
            "term_type": "material",
            "score": 0.70,
            "context_aligned": False,
            "reasons": ["cross_customer_only"],
        },
    ]

    corrected = _apply_knowledge_correction(result, "material", history)

    assert corrected["final_value"] == "PA66 GF30"
    assert corrected["final_source"] == "knowledge_assisted"
    assert corrected["knowledge_trace"] == {
        "original_value": "PA66 GF3O",
        "history_candidate": "PA66 GF30",
        "final_value": "PA66 GF30",
        "decision": "AUTO_CORRECT",
        "score": 0.97,
        "margin": 0.27,
        "reasons": ["fuzzy", "product_context"],
    }


def test_final_result_preserves_field_level_knowledge_trace() -> None:
    structured = _structured("PA66 GF3O")
    name = structured["pages"][0]["product_sections"][0]["formulas"][0][
        "materials"
    ][0]["name"]
    name["field_id"] = "formula_001__material_001__name"
    trace = {
        "original_value": "PA66 GF3O",
        "history_candidate": "PA66 GF30",
        "final_value": "PA66 GF30",
        "decision": "AUTO_CORRECT",
        "score": 0.97,
        "margin": 0.27,
        "reasons": ["fuzzy", "product_context"],
    }
    fusion = {
        "fields": [
            {
                "field_id": "formula_001__material_001__name",
                "final_value": "PA66 GF30",
                "final_source": "knowledge_assisted",
                "final_confidence": 0.97,
                "status": "AUTO_ACCEPT",
                "candidates": [],
                "knowledge_trace": trace,
            }
        ]
    }

    final = project_final_result("job-1", structured, fusion)
    projected = final["pages"][0]["product_sections"][0]["formulas"][0][
        "materials"
    ][0]["name"]

    assert projected["value"] == "PA66 GF30"
    assert projected["source"] == "knowledge_assisted"
    assert projected["knowledge_trace"] == trace


def test_knowledge_changes_final_result_only_through_safe_fusion() -> None:
    structured = _structured("PA66 GF3O")
    history = {
        "formula_001__material_001__name": [
            {
                "value": "PA66 GF30",
                "term_type": "material",
                "score": 0.97,
                "context_aligned": True,
                "reasons": ["fuzzy", "product_context"],
            }
        ]
    }

    fusion = _build_fusion_result(
        structured,
        [_ocr_page("PA66 GF3O")],
        history,
    )
    final = project_final_result("job-1", structured, fusion)
    projected = final["pages"][0]["product_sections"][0]["formulas"][0][
        "materials"
    ][0]["name"]

    assert projected["value"] == "PA66 GF30"
    assert projected["source"] == "knowledge_assisted"
    assert projected["knowledge_trace"]["original_value"] == "PA66 GF3O"


def _assert_history_cannot_override(field_type: str, raw_value: str) -> None:
    result = {
        "final_value": raw_value,
        "final_source": "ocr_vlm_agree",
        "final_confidence": 0.98,
        "status": "AUTO_ACCEPT",
        "reasons": [],
        "candidates": [
            {
                "value": raw_value,
                "source": "ocr_base",
                "confidence": 0.98,
                "evidence": ["p1_t001"],
            }
        ],
    }
    history = [
        {
            "value": "WRONG-HISTORY-VALUE",
            "score": 1.0,
            "context_aligned": True,
            "reasons": ["normalized_exact"],
        }
    ]

    protected = _apply_knowledge_correction(result, field_type, history)

    assert protected["final_value"] == raw_value
    assert protected["knowledge_trace"]["decision"] == "FORBIDDEN"


def test_history_cannot_override_amount() -> None:
    _assert_history_cannot_override("amount", "45")


def test_history_cannot_override_date() -> None:
    _assert_history_cannot_override("date", "2024-01-01")


def test_history_cannot_override_formula_number() -> None:
    _assert_history_cannot_override("formula_no", "配方2")
