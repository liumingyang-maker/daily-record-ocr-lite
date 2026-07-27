from lite_app.knowledge.correction import (
    CorrectionCandidate,
    decide_correction,
)


def _candidate(
    value: str,
    score: float,
    *,
    context_aligned: bool = True,
) -> CorrectionCandidate:
    return CorrectionCandidate(
        value=value,
        score=score,
        context_aligned=context_aligned,
        reasons=("fuzzy",),
    )


def test_unique_high_score_context_match_can_auto_correct() -> None:
    decision = decide_correction(
        field_type="material",
        raw_value="玻纤维",
        candidates=[
            _candidate("玻纤", 0.96),
            _candidate("玻纤粉", 0.71),
        ],
        evidence_present=True,
    )

    assert decision.action == "AUTO_CORRECT"
    assert decision.value == "玻纤"
    assert decision.original_value == "玻纤维"


def test_ambiguous_candidates_are_suggestions_only() -> None:
    decision = decide_correction(
        field_type="product",
        raw_value="G3OA",
        candidates=[
            _candidate("G30A", 0.96),
            _candidate("G30B", 0.92),
        ],
        evidence_present=True,
    )

    assert decision.action == "SUGGEST"
    assert decision.value == "G3OA"


def test_new_name_is_kept_when_score_or_context_is_insufficient() -> None:
    low_score = decide_correction(
        field_type="customer",
        raw_value="新客户",
        candidates=[_candidate("鑫客户", 0.74)],
        evidence_present=True,
    )
    wrong_context = decide_correction(
        field_type="product",
        raw_value="X99",
        candidates=[
            _candidate("X98", 0.99, context_aligned=False),
        ],
        evidence_present=True,
    )

    assert low_score.action == "KEEP_RAW"
    assert wrong_context.action == "SUGGEST"
    assert wrong_context.value == "X99"


def test_numeric_date_and_identifier_fields_are_never_changed() -> None:
    for field_type, raw_value in [
        ("amount", "35-36"),
        ("date", "2024/07/12"),
        ("identifier", "G3OA-01"),
        ("formula_no", "配方2"),
    ]:
        decision = decide_correction(
            field_type=field_type,
            raw_value=raw_value,
            candidates=[_candidate("35", 1.0)],
            evidence_present=True,
        )
        assert decision.action == "FORBIDDEN"
        assert decision.value == raw_value


def test_missing_pixel_or_ocr_evidence_disables_auto_correction() -> None:
    decision = decide_correction(
        field_type="material",
        raw_value="玻纤维",
        candidates=[_candidate("玻纤", 0.99)],
        evidence_present=False,
    )

    assert decision.action == "KEEP_RAW"
    assert decision.value == "玻纤维"
