# Personal Workbench and Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a business-facing formula-card review flow, searchable personal knowledge and lexicon pages, safe import previews, and legacy-style customer Excel exports.

**Architecture:** Keep FastAPI, Jinja and vanilla JavaScript. Build view models that hide internal field identifiers by default, mutate canonical FinalResult through validated APIs, and query the active personal SQLite database. Generate customer workbooks from database records only.

**Tech Stack:** Python 3.11, FastAPI, Jinja2, vanilla JavaScript/CSS, SQLite, openpyxl, pytest.

---

## File map

- `lite_app/review_view.py`: evidence-first card view.
- `lite_app/review_editor.py`: card/material/process/note edits.
- `lite_app/knowledge/query.py`: customer/product/filter queries.
- `lite_app/knowledge/lexicon_admin.py`: alias approval, merge and disable.
- `lite_app/knowledge/personal_exporter.py`: customer/product/ZIP export.
- `lite_app/templates/job.html`: card workbench.
- `lite_app/templates/knowledge.html`: formula timeline.
- `lite_app/templates/lexicon.html`: user-facing lexicon.
- `lite_app/templates/import_knowledge.html`: import preview.
- `lite_app/static/review.js`: autosave and confirm.
- `lite_app/static/knowledge.js`: filters and details.
- `lite_app/static/lexicon.js`: alias actions.
- `lite_app/static/style.css`: responsive evidence/card layout.
- `tests_lite/test_personal_workbench.py`
- `tests_lite/test_personal_knowledge_pages.py`
- `tests_lite/test_personal_exporter.py`

### Task 1: Formula-card review model

- [ ] Write failing tests asserting the default model exposes only conflict, empty,
low-confidence and knowledge-corrected fields while retaining an expandable `all_fields`.

- [ ] Witness red.

- [ ] Extend `review_view.py` to expose customer, product, date, materials, process,
notes, tight/context evidence, correction receipt and business-level pending reasons.
Internal IDs remain data attributes, not visible labels.

- [ ] Run green.

### Task 2: Editable card APIs

- [ ] Write failing API tests for adding/removing/reordering materials, process
parameters and notes; changing customer/product/date; restoring a corrected raw value;
soft-deleting a formula; and confirming one or all clean cards.

- [ ] Witness red.

- [ ] Add version-checked endpoints that validate indexes and field types, mutate
canonical FinalResult atomically, and call the confirmed learning transaction.
Confirmed formula edits overwrite the active business record as approved.

- [ ] Run green plus existing review API tests.

### Task 3: Workbench template and interaction

- [ ] Write failing TestClient assertions that normal card pages contain `证据`,
`识别结果`, `词库辅助`, `确认这条配方`, and do not visibly label `Field ID`,
`Schema`, `BBox`, `Provider` or `Model`.

- [ ] Witness red.

- [ ] Implement side-by-side evidence and editable card layout, default issue-only
folding, add/delete controls, one-card confirmation and batch confirmation. Keep JSON
under a closed `高级工具` details element.

- [ ] Run page and JavaScript contract tests green.

### Task 4: Searchable formula knowledge

- [ ] Write failing query tests for customer, product, date range, material, process,
note keyword, unknown date, pending and soft-deleted filters.

- [ ] Witness red.

- [ ] Implement indexed parameterized SQLite queries and customer → product → ordered
formula results. Unknown-date records use source anchors between dated neighbors.

- [ ] Run green.

### Task 5: User-facing lexicon administration

- [ ] Write failing tests for list/filter, approve alias, reject alias, disable term,
merge duplicates and retrieve correction evidence.

- [ ] Witness red.

- [ ] Implement safe service methods. Reject merges across incompatible term types
and reject any alias operation involving numeric/date/id field categories.

- [ ] Add `/knowledge/lexicon` page with business labels and advanced scores folded.

- [ ] Run green.

### Task 6: Import preview page

- [ ] Write failing tests asserting a package cannot commit before validation and the
preview shows candidate, duplicate, invalid, excluded, lexicon and evidence totals.

- [ ] Witness red.

- [ ] Add `/knowledge/import` routes for local staged data and standard ZIP upload.
Commit requires a current preview token and explicit confirmation.

- [ ] Run green.

### Task 7: Legacy-style Excel exporter

- [ ] Write failing workbook tests:

```python
book = load_workbook(export_customer(db, customer_id))
assert book.sheetnames[0] == "总索引"
assert "G30A" in book.sheetnames
sheet = book["G30A"]
assert sheet["A2"].value == "配方"
assert sheet["A3"].value == "数量"
assert "注意事项" in [cell.value for cell in sheet[6]]
```

Also assert unknown dates show `未知`, formula-like values are Excel-escaped, invalid
sheet names are sanitized, and long products receive stable unique sheet names.

- [ ] Witness red.

- [ ] Implement `personal_exporter.py`. Produce one customer workbook, one product
sheet per product, horizontal blocks, frozen index header, readable widths and a ZIP
of all customer workbooks. Read only confirmed non-deleted database records.

- [ ] Run exporter tests green and visually inspect representative output.

### Task 8: Full workflow E2E

- [ ] Add an E2E test: upload two images, receive multiple cards, edit one material,
confirm cards, query knowledge, find the learned term, export customer workbook, and
soft-delete one formula.

- [ ] Witness red.

- [ ] Add only the minimal route/service integration required for green.

- [ ] Run:

```powershell
python -m pytest tests_lite/test_personal_workbench.py `
  tests_lite/test_personal_knowledge_pages.py `
  tests_lite/test_personal_exporter.py `
  tests_lite/test_user_workflow_e2e.py -q
python -m pytest -m "not real_ocr" -q
python -m ruff check .
git diff --check
```

