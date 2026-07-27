# Knowledge-Assisted Recognition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make OCR + Qwen VLM + the personal knowledge base measurably improve business-text recognition while preventing knowledge from changing quantities, dates, identifiers, or genuinely new names.

**Architecture:** Preserve low-confidence OCR evidence, segment pages into formula cards, retrieve typed context candidates before VLM, fuse field evidence with a margin-gated correction policy, and learn only from confirmed user outcomes. All corrections remain reversible and auditable.

**Tech Stack:** Python 3.11, PP-OCRv6, Qwen3.7 Plus OpenAI-compatible API, SQLite, RapidFuzz, FastAPI, pytest.

---

## File map

- `lite_app/ocr/base.py`: retained low-confidence token state.
- `lite_app/ocr/paddleocr_v6.py`: separate retention and acceptance thresholds.
- `lite_app/recognition/cards.py`: deterministic formula-card segmentation.
- `lite_app/knowledge/lexicon.py`: typed terms, aliases, contexts and feedback.
- `lite_app/knowledge/retrieval.py`: scoped candidate retrieval.
- `lite_app/knowledge/correction.py`: margin-gated decisions.
- `lite_app/fusion/confidence.py`: system-owned evidence score.
- `lite_app/fusion/engine.py`: correction-aware field fusion.
- `lite_app/pipeline_v2.py`: orchestrate cards, retrieval, VLM and recheck.
- `lite_app/review/recheck.py`: include scoped candidates in local recheck.
- `scripts/benchmark_knowledge.py`: real baseline/A-B evaluation.
- `tests_lite/test_knowledge_correction.py`: safety policy.
- `tests_lite/test_formula_cards.py`: segmentation.
- `tests_lite/test_pipeline_knowledge.py`: integration.
- `tests_lite/test_knowledge_learning.py`: confirmation feedback.

### Task 1: Preserve low-confidence OCR evidence

**Files:**
- Modify: `lite_app/ocr/base.py`
- Modify: `lite_app/ocr/paddleocr_v6.py`
- Modify: `lite_app/ocr/manager.py`
- Create: `tests_lite/test_ocr_candidate_retention.py`

- [ ] Write a failing test proving a token at confidence `0.31` is retained as
`candidate_only=True` while a token at `0.82` remains eligible for direct fusion.

- [ ] Run the focused test and verify it fails because the current provider removes
all tokens below `minimum_score`.

- [ ] Add `retention_score` and `acceptance_score`. Keep tokens above retention,
mark tokens below acceptance as candidate-only, and preserve raw score and bbox.

- [ ] Run the focused test and existing OCR adapter tests green.

### Task 2: Formula-card segmentation

**Files:**
- Create: `lite_app/recognition/__init__.py`
- Create: `lite_app/recognition/cards.py`
- Create: `tests_lite/test_formula_cards.py`

- [ ] Write failing tests for one image with two stacked formula blocks, one block
without a date between dated blocks, and two pages that must never merge.

```python
cards = segment_formula_cards(page, layout)
assert [card.card_index for card in cards] == [1, 2]
assert cards[0].source_image_index == cards[1].source_image_index == 1
assert cards[0].bbox[3] <= cards[1].bbox[1]
```

- [ ] Witness red.

- [ ] Implement segmentation from record anchors, horizontal lines, material/amount
pairs, date/title proximity and page boundaries. Ambiguous overlap produces one
review-required card instead of guessed subcards.

- [ ] Run green plus layout regressions.

### Task 3: Typed contextual retrieval

**Files:**
- Create: `lite_app/knowledge/lexicon.py`
- Create: `lite_app/knowledge/retrieval.py`
- Create: `tests_lite/test_knowledge_retrieval.py`

- [ ] Write failing tests showing that `G3OA` ranks `G30A` first for customer `联创`,
but a similarly spelled product from another customer cannot auto-rank into the
same context.

- [ ] Witness red.

- [ ] Implement a typed retrieval request:

```python
@dataclass(frozen=True)
class RetrievalRequest:
    raw_text: str
    term_type: Literal["customer", "product", "material", "process", "note_phrase"]
    customer: str = ""
    product: str = ""
    peer_terms: tuple[str, ...] = ()
    limit: int = 5
```

Rank exact name, normalized exact, approved alias, OCR-error alias and fuzzy matches,
then add bounded context, co-occurrence and accepted-feedback bonuses. Return both
score and individual reasons.

- [ ] Run green and confirm cross-customer tests remain review-only.

### Task 4: Safe correction decisions

**Files:**
- Create: `lite_app/knowledge/correction.py`
- Create: `tests_lite/test_knowledge_correction.py`

- [ ] Write failing tests for unique safe correction, ambiguous top-two candidates,
new-name protection, and forbidden field types.

```python
decision = decide_correction(
    field_type="material",
    raw_value="玻纤维",
    candidates=[
        candidate("玻纤", 0.96),
        candidate("玻纤粉", 0.71),
    ],
    evidence_present=True,
)
assert decision.action == "AUTO_CORRECT"
assert decision.value == "玻纤"

assert decide_correction(
    field_type="amount",
    raw_value="35-36",
    candidates=[candidate("35", 1.0)],
    evidence_present=True,
).action == "FORBIDDEN"
```

- [ ] Witness red.

- [ ] Implement per-type minimum score, top-two margin, context-required flags and
novelty protection. Return `AUTO_CORRECT`, `SUGGEST`, `KEEP_RAW` or `FORBIDDEN`.

- [ ] Run green. Assert amount, date, identifier and free-note values are byte-for-byte
unchanged.

### Task 5: System-owned confidence and fusion

**Files:**
- Create: `lite_app/fusion/confidence.py`
- Modify: `lite_app/fusion/engine.py`
- Modify: `config/fusion_rules.yaml`
- Create: `tests_lite/test_fusion_confidence.py`

- [ ] Write failing tests proving VLM self-confidence alone cannot auto-accept,
OCR+VLM agreement can, and knowledge support cannot override numeric conflict.

- [ ] Witness red.

- [ ] Implement evidence features for OCR quality, OCR/VLM agreement, association,
card boundary, candidate score, candidate margin and feedback trust. Preserve raw
source confidences for audit, but compute `final_confidence` from system features.

- [ ] Run green plus all fusion tests.

### Task 6: Knowledge before and after card VLM

**Files:**
- Modify: `lite_app/pipeline_v2.py`
- Modify: `config/record_schema.yaml`
- Create: `tests_lite/test_pipeline_knowledge.py`

- [ ] Write a failing integration test with two cards. Assert the provider receives
one card request at a time and only scoped typed candidates, then assert the final
result records a reversible correction receipt.

- [ ] Witness red.

- [ ] Refactor orchestration into testable helpers:

```python
async def analyze_card(
    card: FormulaCard,
    ocr_page: OCRPage,
    layout: dict[str, Any],
    retrieval: KnowledgeRetrieval,
    provider: VisionProvider,
) -> CardRecognition:
    ...
```

The prompt explicitly says candidates are references, new names are allowed, and
numbers/dates must come from pixels. Assemble validated cards into record-v1 only
after each card passes its smaller contract.

- [ ] Run green plus multi-page pipeline tests.

### Task 7: Knowledge-aware local recheck

**Files:**
- Modify: `lite_app/review/recheck.py`
- Create: `tests_lite/test_knowledge_recheck.py`

- [ ] Write a failing test asserting a material recheck prompt includes the tight
crop, context crop, field role, customer/product and at most five typed candidates.
Assert amount rechecks contain no historical amount candidate.

- [ ] Witness red.

- [ ] Add scoped context to one-shot recheck and preserve the existing single-recheck
limit. Re-fusion uses the same correction policy as initial recognition.

- [ ] Run green.

### Task 8: Confirmed learning loop

**Files:**
- Create: `lite_app/knowledge/learning.py`
- Modify: `lite_app/review_state.py`
- Create: `tests_lite/test_knowledge_learning.py`

- [ ] Write failing transaction tests asserting confirmation writes formula, canonical
terms, context counts and feedback together. Force an error and assert none persist.

- [ ] Write a failing alias promotion test: one user correction creates an observed
alias; repeated confirmation or explicit approval makes it eligible for auto-correct.

- [ ] Witness red.

- [ ] Implement transaction and cache invalidation. Reject feedback for numeric/date/
identifier fields.

- [ ] Run green plus knowledge history tests.

### Task 9: Real A/B benchmark

**Files:**
- Create: `scripts/benchmark_knowledge.py`
- Create: `config/schema/knowledge-benchmark-v1.schema.json`
- Create: `tests_lite/test_benchmark_knowledge.py`

- [ ] Write failing metric tests for exact text accuracy, auto-correction precision,
review rate, whole-card accuracy, forbidden-field mutation and latency.

- [ ] Witness red.

- [ ] Implement a benchmark that consumes private ignored manifests and writes only
aggregate, redacted JSON. Support baseline OCR, OCR+VLM and OCR+VLM+knowledge modes
on identical samples.

- [ ] Run green.

- [ ] Execute on real uploaded images and real workbook evidence crops. Gate release
on zero wrong auto-corrections, zero numeric/date/id mutations, higher assisted
accuracy and lower review rate.

### Task 10: Full verification

- [ ] Run:

```powershell
python -m pytest tests_lite/test_ocr_candidate_retention.py `
  tests_lite/test_formula_cards.py `
  tests_lite/test_knowledge_retrieval.py `
  tests_lite/test_knowledge_correction.py `
  tests_lite/test_fusion_confidence.py `
  tests_lite/test_pipeline_knowledge.py `
  tests_lite/test_knowledge_recheck.py `
  tests_lite/test_knowledge_learning.py `
  tests_lite/test_benchmark_knowledge.py -q
python -m pytest -m "not real_ocr" -q
python -m ruff check .
git diff --check
```

- [ ] Run real OCR and Qwen gates with private local configuration; keep complete
model content and credentials out of public logs and Git.
