from __future__ import annotations

import copy
from datetime import UTC, datetime
from pathlib import Path

from lite_app.final_result import FinalResultService, project_final_result
from lite_app.knowledge.database import KnowledgeDB
from lite_app.ocr.base import OCRPage, OCRToken
from lite_app.pipeline_v2 import (
    _apply_knowledge_correction,
    _build_compact_qwen_prompt,
    _build_fusion_result,
    _build_knowledge_prompt,
    _formula_regions_by_page,
    _history_candidates,
    _knowledge_assist_enabled,
    _uses_compact_qwen_contract,
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


def _ocr_page_many(*texts: str) -> OCRPage:
    page = _ocr_page(texts[0])
    page.tokens = [
        OCRToken(
            id=f"p1_t{index:03d}",
            text=text,
            confidence=0.92,
            polygon=[[10, 10], [90, 10], [90, 30], [10, 30]],
            bbox=[10, 10, 90, 30],
            center_x=50,
            center_y=20,
        )
        for index, text in enumerate(texts, 1)
    ]
    return page


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
        term_type="customer",
        value="联创",
        customer="联创",
    )
    _seed_term(
        db_path,
        term_type="product",
        value="G30A",
        customer="联创",
    )
    _seed_term(
        db_path,
        term_type="material",
        value="PA66 GF30",
        customer="联创",
        product="G30A",
    )

    prompt = _build_knowledge_prompt(
        [_ocr_page_many("联创", "G30A", "PA66 GF3O")],
        db_path,
    )

    material = next(
        item
        for item in prompt["references"]
        if item["term_type"] == "material"
    )
    assert material["raw_text"] == "PA66 GF3O"
    assert material["candidate"] == "PA66 GF30"
    assert prompt["policy"]["never_override"] == [
        "amount",
        "date",
        "formula_no",
        "identifier",
        "unit",
    ]


def test_prompt_material_candidates_are_scoped_to_inferred_customer_product(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "knowledge.sqlite3"
    _seed_term(
        db_path,
        term_type="customer",
        value="客户B",
        customer="客户B",
    )
    _seed_term(
        db_path,
        term_type="product",
        value="G30A",
        customer="客户B",
    )
    _seed_term(
        db_path,
        term_type="material",
        value="PA66-G30",
        customer="客户A",
        product="G30A",
    )
    _seed_term(
        db_path,
        term_type="material",
        value="PA66-G35",
        customer="客户B",
        product="G30A",
    )

    prompt = _build_knowledge_prompt(
        [_ocr_page_many("客户B", "G30A", "PA66-G30")],
        db_path,
    )

    materials = [
        item["candidate"]
        for item in prompt["references"]
        if item["term_type"] == "material"
    ]
    assert "PA66-G30" not in materials
    assert "PA66-G35" in materials
    assert prompt["context"] == {"customer": "客户B", "product": "G30A"}


def test_compact_qwen_prompt_keeps_business_and_safety_contract() -> None:
    prompt = _build_compact_qwen_prompt(
        instructions="full record-v1 instructions that must not be copied",
        ocr_evidence=[{"image_index": 1, "tokens": [{"id": "p1_t001", "text": "25"}]}],
        layout_prompt={"1": {"records": [{"token_ids": ["p1_t001"]}]}},
        knowledge_prompt={
            "policy": {"never_override": ["amount", "date", "formula_no", "unit"]},
            "context": {"customer": "客户甲", "product": "G30A"},
            "references": [],
        },
    )

    assert "JSON" in prompt
    assert "source_image_index" in prompt
    assert "record_bbox" in prompt
    assert "归一化" in prompt
    assert "company" in prompt
    assert "product_or_series" in prompt
    assert "amount" in prompt
    assert "date" in prompt
    assert "formula_no" in prompt
    assert "unit" in prompt
    assert "只填写可见的数字序号" in prompt
    assert "日期行" in prompt
    assert "只有明确写有“工艺”" in prompt
    assert "逐字符保留" in prompt
    assert "full record-v1 instructions" not in prompt


def test_compact_qwen_contract_is_limited_to_official_alibaba_host() -> None:
    assert _uses_compact_qwen_contract(
        {
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": "qwen3.7-plus",
        }
    )
    assert not _uses_compact_qwen_contract(
        {
            "base_url": "https://dashscope.aliyuncs.com.example.invalid/v1",
            "model": "qwen3.7-plus",
        }
    )
    assert not _uses_compact_qwen_contract(
        {
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": "other-model",
        }
    )


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


def test_same_material_different_customer_is_review(tmp_path: Path) -> None:
    db_path = tmp_path / "knowledge.sqlite3"
    _seed_term(
        db_path,
        term_type="material",
        value="PA66-G30",
        customer="客户A",
        product="G30A",
    )
    structured = _structured("PA66-G3O")
    structured["pages"][0]["company"]["standard_value"] = "客户B"
    matches = _history_candidates(structured, db_path)
    result = {
        "final_value": "PA66-G3O",
        "final_source": "vlm",
        "final_confidence": 0.91,
        "status": "AUTO_ACCEPT",
        "reasons": [],
        "candidates": [
            {
                "value": "PA66-G3O",
                "source": "vlm",
                "confidence": 0.91,
                "evidence": ["p1_t001"],
            }
        ],
    }

    decided = _apply_knowledge_correction(
        result,
        "material",
        matches["formula_001__material_001__name"],
    )

    assert decided["final_value"] == "PA66-G3O"
    assert decided["status"] == "NEED_REVIEW"
    assert decided["knowledge_trace"]["decision"] == "SUGGEST"


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


def test_knowledge_trace_matches_final_value() -> None:
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
    corrected = _apply_knowledge_correction(
        result,
        "material",
        [
            {
                "value": "PA66 GF30",
                "score": 0.97,
                "context_aligned": True,
                "reasons": ["product_context"],
            }
        ],
    )

    assert corrected["knowledge_trace"]["final_value"] == corrected["final_value"]


def test_knowledge_trace_survives_reload(
    tmp_path: Path,
) -> None:
    from tests_lite.test_pipeline_v2_e2e import _vision_result

    strict_result = _vision_result()
    formula = strict_result["pages"][0]["product_sections"][0]["formulas"][0]
    formula["formula_id"] = "formula_001"
    material = formula["materials"][0]
    material["material_id"] = "material_001"
    field_id = "formula_001__material_001__name"
    trace = {
        "original_value": material["name"]["value"],
        "history_candidate": "PA66 GF30",
        "final_value": "PA66 GF30",
        "decision": "AUTO_CORRECT",
        "score": 0.97,
        "margin": 0.97,
        "reasons": ["product_context"],
    }
    final = project_final_result(
        "job-trace",
        strict_result,
        {
            "fields": [
                {
                    "field_id": field_id,
                    "final_value": "PA66 GF30",
                    "final_source": "knowledge_assisted",
                    "final_confidence": 0.97,
                    "status": "AUTO_ACCEPT",
                    "candidates": [],
                    "knowledge_trace": trace,
                }
            ]
        },
    )
    service = FinalResultService(tmp_path / "job")

    service.replace(final)
    loaded = service.load()
    reloaded = loaded["pages"][0]["product_sections"][0]["formulas"][0][
        "materials"
    ][0]["name"]

    assert reloaded["knowledge_trace"] == trace
    assert reloaded["knowledge_trace"]["final_value"] == reloaded["value"]


def test_final_result_contains_all_trace() -> None:
    from tests_lite.test_pipeline_v2_e2e import _vision_result

    structured = _vision_result()
    formula = structured["pages"][0]["product_sections"][0]["formulas"][0]
    formula["formula_id"] = "formula_001"
    first = formula["materials"][0]
    first["material_id"] = "material_001"
    second = copy.deepcopy(first)
    second["material_id"] = "material_002"
    formula["materials"].append(second)
    fields = []
    for index in (1, 2):
        value = f"规范材料{index}"
        fields.append(
            {
                "field_id": f"formula_001__material_{index:03d}__name",
                "final_value": value,
                "final_source": "knowledge_assisted",
                "final_confidence": 0.97,
                "status": "AUTO_ACCEPT",
                "candidates": [],
                "knowledge_trace": {
                    "original_value": "原始材料",
                    "history_candidate": value,
                    "final_value": value,
                    "decision": "AUTO_CORRECT",
                    "score": 0.97,
                    "margin": 0.97,
                    "reasons": ["product_context"],
                },
            }
        )

    final = project_final_result("job-all-traces", structured, {"fields": fields})
    names = [
        material["name"]
        for material in final["pages"][0]["product_sections"][0]["formulas"][0][
            "materials"
        ]
    ]

    assert [name["knowledge_trace"]["final_value"] for name in names] == [
        "规范材料1",
        "规范材料2",
    ]
    assert all(name["knowledge_trace"]["final_value"] == name["value"] for name in names)


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


def test_pipeline_amount_field_type_is_forbidden() -> None:
    structured = _structured()
    material = structured["pages"][0]["product_sections"][0]["formulas"][0][
        "materials"
    ][0]
    material["amount"] = {
        "value": "45",
        "confidence": 0.95,
        "evidence_token_ids": ["p1_t001"],
    }
    fusion = _build_fusion_result(
        structured,
        [_ocr_page("45")],
        {
            "formula_001__material_001__amount": [
                {
                    "value": "50",
                    "score": 1.0,
                    "context_aligned": True,
                    "reasons": ["normalized_exact"],
                }
            ]
        },
    )
    amount = next(
        field
        for field in fusion["fields"]
        if field["field_id"].endswith("__amount")
    )

    assert amount["final_value"] == "45"
    assert amount["knowledge_trace"]["decision"] == "FORBIDDEN"


def test_pipeline_rejects_shared_unanchored_amount_candidate() -> None:
    structured = _structured("Material A")
    formula = structured["pages"][0]["product_sections"][0]["formulas"][0]
    first = formula["materials"][0]
    first["name"] = {"value": "Material A", "confidence": 0.9}
    first["amount"] = {"value": "12", "confidence": 0.9}
    second = copy.deepcopy(first)
    second["material_id"] = "material_002"
    second["name"]["value"] = "Material B"
    second["amount"]["value"] = "7.5"
    formula["materials"] = [first, second]
    page = OCRPage(
        image_index=1,
        width=1000,
        height=1000,
        tokens=[
            OCRToken(
                id="p1_t001",
                text="Material A Material B",
                confidence=0.99,
                polygon=[[100, 100], [420, 100], [420, 140], [100, 140]],
                bbox=[100, 100, 420, 140],
                center_x=260,
                center_y=120,
            ),
            OCRToken(
                id="p1_t002",
                text="123456",
                confidence=0.99,
                polygon=[[100, 170], [260, 170], [260, 210], [100, 210]],
                bbox=[100, 170, 260, 210],
                center_x=180,
                center_y=190,
            ),
        ],
        average_confidence=0.99,
        provider="paddleocr_v6",
        model="PP-OCRv6_medium",
        elapsed_ms=1,
    )
    layout = {
        "pairs": {
            "1": [
                {
                    "name_token_ids": ["p1_t001"],
                    "amount_token_ids": ["p1_t002"],
                    "name": "Material A Material B",
                    "score": 0.99,
                }
            ]
        },
        "records": {"1": [{"bbox": [0, 0, 1000, 1000]}]},
    }

    fusion = _build_fusion_result(structured, [page], {}, layout)
    amounts = {
        field["field_id"]: field
        for field in fusion["fields"]
        if field["field_id"].endswith("__amount")
    }

    assert amounts["formula_001__material_001__amount"]["final_value"] == "12"
    assert amounts["formula_001__material_002__amount"]["final_value"] == "7.5"
    assert all(
        candidate["value"] != "123456"
        for field in amounts.values()
        for candidate in field["candidates"]
    )


def test_pipeline_rejects_same_parameter_from_another_formula_region() -> None:
    structured = _structured("Material A")
    section = structured["pages"][0]["product_sections"][0]
    first_formula = section["formulas"][0]
    first_formula["process_parameters"] = [
        {
            "parameter_id": "parameter_001",
            "name": {"value": "Side Feed", "confidence": 0.9},
            "value": {"value": "8", "confidence": 0.9},
            "unit": {"value": "", "confidence": 0.0},
        }
    ]
    second_formula = copy.deepcopy(first_formula)
    second_formula["formula_id"] = "formula_002"
    second_formula["process_parameters"][0]["value"]["value"] = "7.6"
    section["formulas"] = [first_formula, second_formula]
    page = OCRPage(
        image_index=1,
        width=1000,
        height=1000,
        tokens=[
            OCRToken(
                id="p1_t001",
                text="Side Feed",
                confidence=0.99,
                polygon=[[100, 100], [220, 100], [220, 140], [100, 140]],
                bbox=[100, 100, 220, 140],
                center_x=160,
                center_y=120,
            ),
            OCRToken(
                id="p1_t002",
                text="8",
                confidence=0.99,
                polygon=[[100, 170], [140, 170], [140, 210], [100, 210]],
                bbox=[100, 170, 140, 210],
                center_x=120,
                center_y=190,
            ),
        ],
        average_confidence=0.99,
        provider="paddleocr_v6",
        model="PP-OCRv6_medium",
        elapsed_ms=1,
    )
    layout = {
        "pairs": {
            "1": [
                {
                    "name_token_ids": ["p1_t001"],
                    "amount_token_ids": ["p1_t002"],
                    "name": "Side Feed",
                    "score": 0.99,
                }
            ]
        },
        "records": {"1": []},
        "formula_regions": {
            "1": {
                "formula_001": [0.0, 0.0, 1.0, 0.5],
                "formula_002": [0.0, 0.5, 1.0, 1.0],
            }
        },
    }

    fusion = _build_fusion_result(structured, [page], {}, layout)
    field = next(
        item
        for item in fusion["fields"]
        if item["field_id"] == "formula_002__parameter_001__value"
    )

    assert field["final_value"] == "7.6"
    assert field["final_source"] == "vlm_only"
    assert all(candidate["value"] != "8" for candidate in field["candidates"])


def test_formula_regions_are_resolved_for_every_structured_formula() -> None:
    structured = _structured("Material A")
    section = structured["pages"][0]["product_sections"][0]
    first = section["formulas"][0]
    first["formula_no"] = "Formula 1"
    second = copy.deepcopy(first)
    second["formula_id"] = "formula_002"
    second["formula_no"] = "Formula 2"
    section["formulas"] = [first, second]
    page = OCRPage(
        image_index=1,
        width=1000,
        height=1000,
        tokens=[
            OCRToken(
                id="p1_t001",
                text="Formula 1",
                confidence=0.99,
                polygon=[[50, 100], [180, 100], [180, 140], [50, 140]],
                bbox=[50, 100, 180, 140],
                center_x=115,
                center_y=120,
            ),
            OCRToken(
                id="p1_t002",
                text="Formula 2",
                confidence=0.99,
                polygon=[[50, 600], [180, 600], [180, 640], [50, 640]],
                bbox=[50, 600, 180, 640],
                center_x=115,
                center_y=620,
            ),
        ],
        average_confidence=0.99,
        provider="paddleocr_v6",
        model="PP-OCRv6_medium",
        elapsed_ms=1,
    )

    regions = _formula_regions_by_page(
        structured,
        [page],
        {"1": {"lines": [], "pairs": [], "records": []}},
    )

    assert set(regions["1"]) == {"formula_001", "formula_002"}
    assert regions["1"]["formula_001"][3] <= regions["1"]["formula_002"][1]


def test_pipeline_date_field_type_is_forbidden() -> None:
    structured = _structured()
    formula = structured["pages"][0]["product_sections"][0]["formulas"][0]
    formula["record_date"] = {"value": "2024-01-01"}
    final = project_final_result(
        "job-date",
        structured,
        _build_fusion_result(
            structured,
            [_ocr_page("2024-01-01")],
            {"formula_001__record_date": [{"value": "2025-01-01", "score": 1.0}]},
        ),
    )

    assert formula["record_date"]["value"] == "2024-01-01"
    assert final["pages"][0]["product_sections"][0]["formulas"][0][
        "record_date"
    ]["value"] == "2024-01-01"


def test_pipeline_recovers_formula_local_date_as_review_only() -> None:
    structured = _structured("Material A")
    formula = structured["pages"][0]["product_sections"][0]["formulas"][0]
    formula["record_date"] = {"value": "", "confidence": 0.0}
    page = OCRPage(
        image_index=1,
        width=1000,
        height=1000,
        tokens=[
            OCRToken(
                id="p1_t001",
                text="22/9/3 (kg)",
                confidence=0.94,
                polygon=[[80, 160], [260, 160], [260, 200], [80, 200]],
                bbox=[80, 160, 260, 200],
                center_x=170,
                center_y=180,
            )
        ],
        average_confidence=0.94,
        provider="paddleocr_v6",
        model="PP-OCRv6_medium",
        elapsed_ms=1,
    )
    layout = {
        "pairs": {"1": []},
        "records": {"1": []},
        "formula_regions": {"1": {"formula_001": [0.0, 0.0, 1.0, 0.5]}},
    }

    fusion = _build_fusion_result(structured, [page], {}, layout)
    field = next(
        item
        for item in fusion["fields"]
        if item["field_id"] == "formula_001__record_date"
    )
    final = project_final_result("job-date-recovery", structured, fusion)
    projected = final["pages"][0]["product_sections"][0]["formulas"][0][
        "record_date"
    ]

    assert field["final_value"] == "22/9/3"
    assert field["status"] == "NEED_REVIEW"
    assert field["association"]["method"] == "formula_local_date"
    assert projected["value"] == "22/9/3"
    assert projected["status"] == "NEED_REVIEW"


def test_pipeline_does_not_replace_existing_vlm_date() -> None:
    structured = _structured("Material A")
    formula = structured["pages"][0]["product_sections"][0]["formulas"][0]
    formula["record_date"] = {"value": "24.7.19", "confidence": 0.9}
    page = _ocr_page("22/9/3")
    layout = {
        "pairs": {"1": []},
        "records": {"1": []},
        "formula_regions": {"1": {"formula_001": [0.0, 0.0, 1.0, 0.5]}},
    }

    fusion = _build_fusion_result(structured, [page], {}, layout)
    field = next(
        item
        for item in fusion["fields"]
        if item["field_id"] == "formula_001__record_date"
    )

    assert field["final_value"] == "24.7.19"
    assert [candidate["value"] for candidate in field["candidates"]] == ["24.7.19"]


def test_formula_number_never_auto_correct() -> None:
    structured = _structured()
    formula = structured["pages"][0]["product_sections"][0]["formulas"][0]
    formula["formula_no"] = "配方2"
    final = project_final_result(
        "job-formula-no",
        structured,
        _build_fusion_result(
            structured,
            [_ocr_page("配方2")],
            {"formula_001__formula_no": [{"value": "配方1", "score": 1.0}]},
        ),
    )

    assert final["pages"][0]["product_sections"][0]["formulas"][0][
        "formula_no"
    ] == "配方2"
