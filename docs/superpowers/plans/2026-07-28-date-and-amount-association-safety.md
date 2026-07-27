# Date and Amount Association Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent unanchored OCR quantity tokens from overwriting multiple VLM fields, recover only uniquely valid local dates when VLM leaves them empty, and make every knowledge read/write use one configurable private database path.

**Architecture:** Keep whole-image OCR and VLM unchanged. Tighten the existing layout association boundary so only field-anchored material/amount pairs may enter Fusion, add a small date-recovery module that emits review-only OCR candidates from formula-local evidence, and centralize the knowledge database path resolver so the private runtime cannot split reads and writes across databases.

**Tech Stack:** Python 3.11, pytest, FastAPI, SQLite, PP-OCRv6 evidence, existing FusionEngine and FinalResult projection.

---

### Task 1: Reject unanchored, cross-formula, and reusable numeric candidates

**Files:**
- Modify: `lite_app/fusion/association.py`
- Modify: `lite_app/evidence_regions.py`
- Modify: `lite_app/pipeline_v2.py`
- Test: `tests_lite/test_v1_contracts.py`
- Test: `tests_lite/test_pipeline_knowledge.py`

- [ ] **Step 1: Write the failing association test**

Add a test that builds a page with a coarse material row and a concatenated numeric OCR token, passes an amount `FieldEvidence` without a record bbox, material token ids, or material bbox, and asserts `associate_ocr_candidates(...) == []`.

```python
def test_layout_fallback_rejects_unanchored_coarse_amount_pair():
    field = FieldEvidence(
        field_id="formula_001__material_001__amount",
        field_type="amount",
        vlm_value="12",
        source_image_index=1,
        record_bbox=None,
        anchor_value="Material A",
    )
    candidates = associate_ocr_candidates(field, [page], layout)
    assert candidates == []
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests_lite/test_v1_contracts.py -k "unanchored_coarse_amount_pair" -q`

Expected: FAIL because the current `_from_layout()` accepts the highest-scoring pair even without a field-level anchor.

- [ ] **Step 3: Implement the minimal field-anchor gate**

In `_from_layout()`, compute whether each pair is supported by at least one reliable material anchor:

```python
token_anchor = bool(name_ids.intersection(field.anchor_token_ids))
text_anchor = bool(
    field.anchor_value
    and pair_name
    and pair_name == _normalize_text(field.anchor_value)
)
bbox_anchor = bool(
    field.anchor_bbox and name_bbox and _iou(field.anchor_bbox, name_bbox) >= 0.05
)
if not (token_anchor or text_anchor or bbox_anchor):
    continue
```

Retain the existing record-boundary filtering and ambiguity margin. A text-only anchor is insufficient unless the candidate is also inside the current formula region. Do not split or repair concatenated numeric text.

- [ ] **Step 4: Run association tests and verify GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests_lite/test_v1_contracts.py -k "layout_fallback" -q`

Expected: the new rejection test and the existing anchored-layout test both PASS.

- [ ] **Step 5: Write a failing pipeline regression test**

Add a synthetic two-material record whose VLM amounts differ while layout exposes one unanchored OCR amount token. Call `_build_fusion_result()` and assert both projected final values remain their respective VLM values and the shared OCR token is absent from both amount candidates.

```python
amount_fields = {
    field["field_id"]: field
    for field in fusion["fields"]
    if field["field_id"].endswith("__amount")
}
assert amount_fields["formula_001__material_001__amount"]["final_value"] == "12"
assert amount_fields["formula_001__material_002__amount"]["final_value"] == "7.5"
```

Add a process-parameter regression with two formulas containing the same parameter name. The later formula's VLM value is `7.6`; an OCR value `8` belongs to the earlier formula. Assert the later formula remains `7.6` and does not cite the earlier token.

```python
assert fields["formula_002__parameter_001__value"]["final_value"] == "7.6"
assert fields["formula_002__parameter_001__value"]["final_source"] == "vlm_only"
```

- [ ] **Step 6: Run the pipeline regression and verify behavior**

Run: `.venv\Scripts\python.exe -m pytest tests_lite/test_pipeline_knowledge.py -k "shared_unanchored_amount" -q`

Expected before Task 1 implementation: FAIL with the same OCR value reused or with a numeric token taken from another formula. Expected after Task 1 implementation: PASS.

- [ ] **Step 7: Pass resolved formula regions into numeric association**

Expose the existing evidence-region resolver as `resolve_page_formula_regions(...)`. Before Fusion, resolve regions from the structured formulas, OCR pages, and layout anchors, store them under `layout_association["formula_regions"]`, and use the matching formula region when `record_bbox` is absent. This same public resolver is reused by Task 2 date recovery and by review evidence generation.

- [ ] **Step 8: Commit the amount safety change**

```powershell
git add lite_app/fusion/association.py lite_app/evidence_regions.py lite_app/pipeline_v2.py tests_lite/test_v1_contracts.py tests_lite/test_pipeline_knowledge.py
git commit -m "fix: reject unanchored OCR amount candidates"
```

### Task 2: Recover formula-local dates as review-only evidence

**Files:**
- Create: `lite_app/fusion/date_recovery.py`
- Modify: `lite_app/evidence_regions.py`
- Modify: `lite_app/pipeline_v2.py`
- Create: `tests_lite/test_date_recovery.py`
- Modify: `tests_lite/test_pipeline_knowledge.py`

- [ ] **Step 1: Write failing date parser tests**

Create parameterized tests for `22/9/3`, `22/9/19`, `22/9/27`, `22/12/12`, `23/1/7`, `24.7.10`, and `24.7.19`. Assert the raw spelling is retained and the internal sortable date maps the two-digit year to 2000+.

```python
@pytest.mark.parametrize(
    ("raw", "sort_date"),
    [("22/9/3", "2022-09-03"), ("24.7.19", "2024-07-19")],
)
def test_parse_date_candidate_preserves_raw_text(raw, sort_date):
    parsed = parse_date_candidate(raw)
    assert parsed.raw == raw
    assert parsed.sort_date == sort_date
```

Also assert invalid calendar dates, incomplete dates, ordinary quantities, and ambiguous strings return `None`.

- [ ] **Step 2: Run parser tests and verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests_lite/test_date_recovery.py -q`

Expected: collection error because `lite_app.fusion.date_recovery` does not yet exist.

- [ ] **Step 3: Implement the strict date parser**

Create `parse_date_candidate(text)` using a bounded date-shaped match and `datetime.date` validation. It must preserve the matched raw text, derive only a sort key, reject multiple valid matches in one text, and never alter field values.

```python
@dataclass(frozen=True)
class ParsedDateCandidate:
    raw: str
    sort_date: str

def parse_date_candidate(text: str) -> ParsedDateCandidate | None:
    matches = list(_DATE_PATTERN.finditer(text))
    if len(matches) != 1:
        return None
    # validate calendar date; preserve match.group(0)
```

- [ ] **Step 4: Reuse the formula-region resolver exposed in Task 1**

Use `resolve_page_formula_regions(...)` without changing its behavior so numeric association, date recovery, and review crops share the same region boundaries.

- [ ] **Step 5: Write failing scoped recovery tests**

Test `recover_formula_date(...)` with two formula regions on one page. Assert it returns the one valid date in the requested region, rejects two valid dates in one region, rejects a neighboring formula's date, and returns no candidate when the VLM date is already populated.

```python
candidate = recover_formula_date(
    formula_id="formula_001",
    vlm_value="",
    source_image_index=1,
    page=page,
    formula_regions=regions,
)
assert candidate.value == "22/9/3"
assert candidate.requires_review is True
```

- [ ] **Step 6: Run scoped recovery tests and verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests_lite/test_date_recovery.py -k "recover_formula_date" -q`

Expected: FAIL because `recover_formula_date(...)` is not implemented.

- [ ] **Step 7: Implement local date recovery**

Use only OCR tokens whose normalized center is inside the formula region. Search their original text for exactly one valid date; if the region has zero or multiple unique dates, return `None`. Return a `Candidate(source="ocr_base", ...)`-compatible payload with token ids, bbox, raw value, and `requires_review=True`.

- [ ] **Step 8: Write a failing Fusion/FinalResult date projection test**

Build a record with an empty VLM `record_date`, local date evidence, and assert `_build_fusion_result()` creates a `formula_001__record_date` field whose value preserves the original spelling and whose status is `NEED_REVIEW`. Add a companion assertion that a populated VLM date is not replaced.

- [ ] **Step 9: Wire date recovery into the pipeline**

Pass page layout records and formula regions into `_build_fusion_result()`. Before material fields, create one `record_date` Fusion field per record. If VLM has a value, fuse only that value. If VLM is empty and recovery is unique, add the OCR candidate and force review. Do not use history candidates for dates.

- [ ] **Step 10: Run date and projection tests and verify GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests_lite/test_date_recovery.py tests_lite/test_pipeline_knowledge.py -q`

Expected: PASS; original date text remains unchanged in FinalResult projection.

- [ ] **Step 11: Commit the date recovery change**

```powershell
git add lite_app/fusion/date_recovery.py lite_app/evidence_regions.py lite_app/pipeline_v2.py tests_lite/test_date_recovery.py tests_lite/test_pipeline_knowledge.py
git commit -m "fix: recover formula-local dates for review"
```

### Task 3: Centralize the private knowledge database path

**Files:**
- Create: `lite_app/knowledge/path.py`
- Modify: `lite_app/pipeline_v2.py`
- Modify: `lite_app/main.py`
- Modify: `lite_app/exporter.py`
- Modify: `lite_app/grouping/review.py`
- Create: `tests_lite/test_knowledge_path.py`

- [ ] **Step 1: Write failing resolver tests**

Assert `resolve_knowledge_db_path()` uses `KNOWLEDGE_DB_PATH` when present, otherwise returns `DATA_ROOT / "knowledge.sqlite3"`, and always produces an absolute resolved path.

```python
def test_resolver_uses_private_database_override(monkeypatch, tmp_path):
    expected = tmp_path / "private.sqlite3"
    monkeypatch.setenv("KNOWLEDGE_DB_PATH", str(expected))
    assert resolve_knowledge_db_path() == expected.resolve()
```

- [ ] **Step 2: Run the resolver tests and verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests_lite/test_knowledge_path.py -q`

Expected: collection error because the resolver module does not exist.

- [ ] **Step 3: Implement one resolver and replace split paths**

Create:

```python
def resolve_knowledge_db_path() -> Path:
    configured = os.environ.get("KNOWLEDGE_DB_PATH")
    return Path(configured or DATA_ROOT / "knowledge.sqlite3").expanduser().resolve()
```

Replace runtime `KnowledgeDB(DATA_ROOT / "knowledge.sqlite3")` and duplicate private helper implementations in `main.py`, `pipeline_v2.py`, `exporter.py`, and `grouping/review.py`. Explicit constructor arguments remain authoritative for tests and callers.

- [ ] **Step 4: Add a read/write consistency regression**

With `KNOWLEDGE_DB_PATH` pointing at a temporary database, write a known synthetic formula through the confirmation/history path and read it through the knowledge tree/export path. Assert no default `data/knowledge.sqlite3` is consulted or created in the temporary test data root.

- [ ] **Step 5: Run knowledge tests and verify GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests_lite/test_knowledge_path.py tests_lite/test_knowledge_pages.py tests_lite/test_knowledge_learning.py tests_lite/test_knowledge_exporter.py -q`

Expected: PASS; all paths resolve to the configured private database.

- [ ] **Step 6: Commit the path consistency change**

```powershell
git add lite_app/knowledge/path.py lite_app/pipeline_v2.py lite_app/main.py lite_app/exporter.py lite_app/grouping/review.py tests_lite/test_knowledge_path.py
git commit -m "fix: unify private knowledge database path"
```

### Task 4: Verify locally and run a new real-image Gate

**Files:**
- Modify: `docs/audits/PR9_REVIEW_REMEDIATION_WIP.md` if this is the active PR #9 audit file
- Create: `docs/audits/PR9_DATE_AMOUNT_FIX_AUDIT.md`

- [ ] **Step 1: Run focused regression suites**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests_lite/test_v1_contracts.py tests_lite/test_date_recovery.py tests_lite/test_pipeline_knowledge.py tests_lite/test_knowledge_path.py -q
```

Expected: all focused tests PASS.

- [ ] **Step 2: Run repository quality Gates**

Run:

```powershell
.venv\Scripts\ruff.exe check .
git diff --check
.venv\Scripts\python.exe -m pytest -m "not real_ocr" -q
git grep -n -E 'sk-(ws|sp)-[A-Za-z0-9._-]+'
git diff HEAD~3 | Select-String -Pattern 'sk-(ws|sp)-[A-Za-z0-9._-]+'
```

Expected: Ruff clean, diff check clean, all non-real tests pass, and both secret scans return no real key.

- [ ] **Step 3: Verify private artifacts remain untracked**

Run `git status --short --ignored data` and confirm the database, backups, settings, secrets, jobs, evidence, raw responses, and logs are ignored and absent from tracked changes. Do not delete the user's local files.

- [ ] **Step 4: Create a new Job from the same source images**

Use the running private instance and the same two source images to create a new Job. Never edit the old Job directory. Record only sanitized timings, statuses, candidate counts, and artifact existence.

- [ ] **Step 5: Check the real Gate**

Verify:

- the shared concatenated OCR token does not overwrite multiple quantities;
- VLM quantities remain independent;
- uniquely recoverable dates appear as review-only raw text, while ambiguous dates remain empty;
- existing VLM dates remain unchanged;
- `structured_result.json`, Fusion result, FinalResult, and formula evidence crops exist;
- the Job reaches `REVIEW_REQUIRED` without fabricating confirmation, READY, or Excel completion.

- [ ] **Step 6: Write the sanitized audit report**

Document branch SHA, focused/full test counts, Ruff, diff and secret scans, artifact existence, real Gate results, private-data exclusions, and the remaining release blockers. Do not include API keys, private formula values, source-image content, local absolute paths, raw model responses, or private database contents.

### Task 5: Independent review and Draft PR update

**Files:**
- Modify: `docs/audits/PR9_DATE_AMOUNT_FIX_AUDIT.md`

- [ ] **Step 1: Request independent GPT review**

Provide the reviewer with the sanitized diff and audit report. Ask for P0/P1/P2 findings, explicit review of amount fail-closed behavior, date non-guessing behavior, knowledge-path consistency, Secret/private-data boundaries, and whether the change may be pushed while PR #9 remains Draft.

- [ ] **Step 2: Resolve blocking findings**

For every P0/P1 code finding, reproduce it with a failing test, implement the minimal fix, rerun focused and full Gates, and update the audit report. P2 residual risks may remain only when clearly documented and outside this fix's approved scope.

- [ ] **Step 3: Push without changing PR state**

Push `feat/personal-knowledge-layer` to its existing remote branch. Confirm PR #9 is still Draft. Do not merge, tag, or release.

- [ ] **Step 4: Deliver the copyable audit report**

Return the branch SHA, PR link and Draft state, commits, test count, Ruff/diff/Secret results, sanitized real Job Gate, independent GPT conclusion, and remaining blockers in one copyable Markdown block.
