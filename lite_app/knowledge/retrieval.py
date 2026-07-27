"""Typed, context-scoped retrieval from the recognition lexicon."""

from __future__ import annotations

import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from rapidfuzz import fuzz

TermType = Literal[
    "customer",
    "product",
    "material",
    "process",
    "note_phrase",
]


@dataclass(frozen=True)
class RetrievalRequest:
    raw_text: str
    term_type: TermType
    customer: str = ""
    product: str = ""
    peer_terms: tuple[str, ...] = ()
    limit: int = 5


@dataclass(frozen=True)
class RetrievalCandidate:
    value: str
    term_type: TermType
    score: float
    context_aligned: bool
    reasons: tuple[str, ...]


class KnowledgeRetrieval:
    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)

    def retrieve(
        self,
        request: RetrievalRequest,
    ) -> tuple[RetrievalCandidate, ...]:
        if not request.raw_text.strip() or request.limit <= 0:
            return ()
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            terms = connection.execute(
                """
                SELECT id, term_type, standard_value, normalized_value,
                       source_quality, occurrence_count,
                       accepted_count, rejected_count
                FROM lexicon_terms
                WHERE term_type = ? AND enabled = 1
                """,
                (request.term_type,),
            ).fetchall()
            candidates = [
                self._score_term(connection, request, row)
                for row in terms
            ]
        finally:
            connection.close()
        candidates = [
            candidate
            for candidate in candidates
            if candidate.score >= 0.55
        ]
        candidates.sort(
            key=lambda item: (
                item.score,
                item.context_aligned,
                item.value,
            ),
            reverse=True,
        )
        return tuple(candidates[: min(request.limit, 5)])

    def _score_term(
        self,
        connection: sqlite3.Connection,
        request: RetrievalRequest,
        term: sqlite3.Row,
    ) -> RetrievalCandidate:
        raw = _normalize(request.raw_text)
        standard = _normalize(str(term["standard_value"]))
        reasons: list[str] = []
        if raw == standard:
            base_score = 1.0
            reasons.append("normalized_exact")
        else:
            aliases = connection.execute(
                """
                SELECT alias, status FROM lexicon_aliases
                WHERE term_id = ? AND status <> 'rejected'
                """,
                (term["id"],),
            ).fetchall()
            alias_scores = [
                (
                    _similarity(raw, _normalize(str(alias["alias"]))),
                    str(alias["status"]),
                )
                for alias in aliases
            ]
            standard_score = _similarity(raw, standard)
            base_score = standard_score
            reasons.append("fuzzy")
            if alias_scores:
                alias_score, alias_status = max(alias_scores)
                if alias_score > base_score:
                    base_score = alias_score
                    reasons.append(
                        "approved_alias"
                        if alias_status == "approved"
                        else "observed_alias"
                    )
        contexts = connection.execute(
            """
            SELECT customer_context, product_context, occurrence_count,
                   accepted_count, rejected_count
            FROM lexicon_context_stats WHERE term_id = ?
            """,
            (term["id"],),
        ).fetchall()
        context_aligned, context_reason = _context_alignment(
            request,
            contexts,
        )
        if context_reason:
            reasons.append(context_reason)
        score = base_score
        if term["source_quality"] == "confirmed":
            score += 0.02
            reasons.append("confirmed")
        if context_aligned and (request.customer or request.product):
            score += 0.06
        elif request.customer or request.product:
            score -= 0.12
        accepted = int(term["accepted_count"] or 0)
        rejected = int(term["rejected_count"] or 0)
        if accepted > rejected:
            score += min(0.03, (accepted - rejected) * 0.005)
            reasons.append("accepted_feedback")
        return RetrievalCandidate(
            value=str(term["standard_value"]),
            term_type=request.term_type,
            score=round(max(0.0, min(1.0, score)), 4),
            context_aligned=context_aligned,
            reasons=tuple(dict.fromkeys(reasons)),
        )


def _context_alignment(
    request: RetrievalRequest,
    contexts: list[sqlite3.Row],
) -> tuple[bool, str]:
    if not request.customer and not request.product:
        return True, ""
    customer = _normalize(request.customer)
    product = _normalize(request.product)
    for context in contexts:
        customer_match = not customer or (
            _normalize(str(context["customer_context"])) == customer
        )
        product_match = not product or (
            _normalize(str(context["product_context"])) == product
        )
        if customer_match and product_match:
            return True, (
                "product_context" if product else "customer_context"
            )
    if request.customer and contexts:
        return False, "cross_customer_only"
    return False, "context_missing"


def _similarity(left: str, right: str) -> float:
    direct = fuzz.ratio(left, right) / 100.0
    ocr = fuzz.ratio(_ocr_fold(left), _ocr_fold(right)) / 100.0
    return max(direct, min(0.97, ocr))


def _ocr_fold(value: str) -> str:
    return value.translate(str.maketrans({"o": "0", "i": "1", "l": "1"}))


def _normalize(value: str) -> str:
    return " ".join(
        unicodedata.normalize("NFKC", value).casefold().split()
    )
