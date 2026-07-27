"""Safety policy for reversible knowledge-assisted text corrections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

CorrectionAction = Literal[
    "AUTO_CORRECT",
    "SUGGEST",
    "KEEP_RAW",
    "FORBIDDEN",
]
FORBIDDEN_FIELD_TYPES = {
    "amount",
    "date",
    "identifier",
    "formula_no",
    "unit",
}
AUTO_CORRECT_FIELD_TYPES = {
    "customer",
    "product",
    "material",
    "process",
}


@dataclass(frozen=True)
class CorrectionCandidate:
    value: str
    score: float
    context_aligned: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class CorrectionDecision:
    action: CorrectionAction
    value: str
    original_value: str
    candidate_value: str = ""
    score: float = 0.0
    margin: float = 0.0
    reasons: tuple[str, ...] = ()


def decide_correction(
    *,
    field_type: str,
    raw_value: str,
    candidates: Sequence[CorrectionCandidate],
    evidence_present: bool,
    minimum_score: float = 0.92,
    minimum_margin: float = 0.08,
) -> CorrectionDecision:
    """Apply knowledge only when evidence, uniqueness and context all agree."""
    if field_type in FORBIDDEN_FIELD_TYPES:
        return CorrectionDecision(
            action="FORBIDDEN",
            value=raw_value,
            original_value=raw_value,
            reasons=("field_type_forbidden",),
        )
    if field_type not in AUTO_CORRECT_FIELD_TYPES or not evidence_present:
        return CorrectionDecision(
            action="KEEP_RAW",
            value=raw_value,
            original_value=raw_value,
            reasons=(
                "missing_evidence"
                if not evidence_present
                else "field_type_not_supported",
            ),
        )
    ranked = sorted(candidates, key=lambda item: item.score, reverse=True)
    if not ranked:
        return CorrectionDecision(
            action="KEEP_RAW",
            value=raw_value,
            original_value=raw_value,
            reasons=("no_candidate",),
        )
    top = ranked[0]
    runner_up = ranked[1].score if len(ranked) > 1 else 0.0
    margin = max(0.0, top.score - runner_up)
    common = {
        "value": raw_value,
        "original_value": raw_value,
        "candidate_value": top.value,
        "score": top.score,
        "margin": margin,
        "reasons": top.reasons,
    }
    if top.score < 0.80:
        return CorrectionDecision(action="KEEP_RAW", **common)
    if (
        top.score >= minimum_score
        and margin >= minimum_margin
        and top.context_aligned
    ):
        return CorrectionDecision(
            action="AUTO_CORRECT",
            value=top.value,
            original_value=raw_value,
            candidate_value=top.value,
            score=top.score,
            margin=margin,
            reasons=top.reasons,
        )
    return CorrectionDecision(action="SUGGEST", **common)
