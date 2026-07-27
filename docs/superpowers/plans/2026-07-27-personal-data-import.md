# Personal Data Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the user's mixed legacy workbook collection into a validated personal formula database, evidence bundle, exclusion report, and reusable AI ZIP import protocol without modifying source files.

**Architecture:** Add a read-only scanner, format adapters for XLSX/XLS, a conservative formula-block extractor, deterministic staging records, cell-range evidence rendering, and a manifest/checksum package validator. Extraction writes staging artifacts first; only validated high-confidence records are transactionally imported.

**Tech Stack:** Python 3.11, SQLite, openpyxl, xlrd, Pillow, jsonschema, pytest, Ruff.

---

## Working conventions

- Work in `C:\Users\97020\.config\superpowers\worktrees\daily-record-ocr-lite\desktop-installers`.
- Read sources only from `C:\Users\97020\Downloads\各个单位`.
- Exclude `C:\Users\97020\Downloads\__MACOSX` completely.
- Never move, rename, edit, delete, or stage source documents.
- Run all Python commands with `C:\Users\97020\Desktop\daily-record-ocr-lite\.venv\Scripts\python.exe`.
- Each production change must follow a witnessed red-green-refactor cycle.

## File map

- `lite_app/knowledge/import_models.py`: typed staging records and stable fingerprints.
- `lite_app/knowledge/source_scanner.py`: allowlist/exclusion classification.
- `lite_app/knowledge/workbook_reader.py`: common XLSX/XLS cell model.
- `lite_app/knowledge/formula_extractor.py`: conservative block extraction.
- `lite_app/knowledge/evidence_renderer.py`: tight/context evidence PNGs.
- `lite_app/knowledge/import_service.py`: staging, dedupe, transaction, reports.
- `lite_app/knowledge/package.py`: AI ZIP manifest/checksum/schema validation.
- `scripts/import_personal_history.py`: CLI entry point.
- `config/schema/knowledge-package-v1.schema.json`: manifest and record contract.
- `docs/AI_KNOWLEDGE_PACKAGE.md`: instructions and copyable AI prompt.
- `tests_lite/test_source_scanner.py`: file boundary tests.
- `tests_lite/test_formula_extractor.py`: formula block tests.
- `tests_lite/test_knowledge_package.py`: ZIP security and contract tests.
- `tests_lite/test_personal_import.py`: end-to-end staging/import tests.

### Task 1: Source classification

**Files:**
- Create: `lite_app/knowledge/source_scanner.py`
- Create: `tests_lite/test_source_scanner.py`

- [ ] **Step 1: Write failing classification tests**

```python
from pathlib import Path

from lite_app.knowledge.source_scanner import classify_source


def test_macos_metadata_is_always_excluded():
    result = classify_source(Path("__MACOSX/联创/._联创.xlsx"))
    assert result.action == "exclude"
    assert result.reason == "MACOS_METADATA"


def test_formula_named_xlsx_is_candidate():
    result = classify_source(Path("博厚/博厚配方.xlsx"))
    assert result.action == "candidate"
    assert result.customer_hint == "博厚"


def test_report_and_contract_are_excluded():
    assert classify_source(Path("1报告合集/检测报告.xlsx")).action == "exclude"
    assert classify_source(Path("其他/购销合同.xlsx")).action == "exclude"
```

- [ ] **Step 2: Run the focused test and witness failure**

Run:

```powershell
& 'C:\Users\97020\Desktop\daily-record-ocr-lite\.venv\Scripts\python.exe' `
  -m pytest tests_lite/test_source_scanner.py -q
```

Expected: collection fails because `source_scanner` does not exist.

- [ ] **Step 3: Implement immutable classification records and conservative rules**

```python
@dataclass(frozen=True)
class SourceDecision:
    path: Path
    action: Literal["candidate", "exclude", "review"]
    reason: str
    customer_hint: str = ""


def classify_source(relative_path: Path) -> SourceDecision:
    parts = relative_path.parts
    name = relative_path.name
    if "__MACOSX" in parts or name.startswith("._") or name == ".DS_Store":
        return SourceDecision(relative_path, "exclude", "MACOS_METADATA")
    if relative_path.suffix.lower() not in {".xlsx", ".xls"}:
        return SourceDecision(relative_path, "exclude", "UNSUPPORTED_FORMAT")
    if any(token in str(relative_path) for token in EXCLUDED_BUSINESS_TOKENS):
        return SourceDecision(relative_path, "exclude", "NON_FORMULA_DOCUMENT")
    customer = parts[0] if len(parts) > 1 else ""
    return SourceDecision(relative_path, "candidate", "FORMULA_WORKBOOK", customer)
```

- [ ] **Step 4: Run the focused test green**

Expected: all source scanner tests pass.

### Task 2: Unified workbook cell model

**Files:**
- Create: `lite_app/knowledge/workbook_reader.py`
- Modify: `requirements.txt`
- Modify: `requirements-desktop.txt`
- Create: `tests_lite/test_workbook_reader.py`

- [ ] **Step 1: Write XLSX and XLS adapter tests**

The tests create one XLSX fixture with openpyxl and one checked-in minimal XLS fixture.
Both must produce:

```python
WorkbookData(
    sheets=[
        SheetData(
            name="G30A",
            rows=[
                [CellData(row=1, column=1, value="G30A")],
                [CellData(row=2, column=1, value="配方"),
                 CellData(row=2, column=2, value="PA6")],
            ],
        )
    ]
)
```

- [ ] **Step 2: Witness red**

Run `python -m pytest tests_lite/test_workbook_reader.py -q`.

- [ ] **Step 3: Implement read-only adapters**

Use `openpyxl.load_workbook(path, read_only=False, data_only=True, keep_links=False)`
for XLSX and `xlrd.open_workbook(path, on_demand=True)` for XLS. Convert Excel date
cells to ISO dates only when the workbook marks them as dates; otherwise retain the
raw number and let the extractor inspect surrounding labels.

- [ ] **Step 4: Add pinned XLS dependency**

Add `xlrd==2.0.1` to core and desktop requirements, install it in the development
venv, and run the adapter tests green.

### Task 3: Formula block extraction

**Files:**
- Create: `lite_app/knowledge/import_models.py`
- Create: `lite_app/knowledge/formula_extractor.py`
- Create: `tests_lite/test_formula_extractor.py`

- [ ] **Step 1: Write failing tests for the approved block grammar**

```python
def test_extracts_material_amount_process_date_and_notes():
    sheet = sheet_from_rows(
        "G30A",
        [
            ["G30A", None, 45220],
            ["配方", "PA6", "玻纤", "增韧剂"],
            [None, "55", "35-36", "2（加到3%）"],
            ["工艺", "主机", "喂料"],
            [None, "300", "25"],
            ["注意", "客户要求保持黑度"],
        ],
    )
    records = extract_formula_blocks(sheet, customer_hint="联创")
    assert len(records) == 1
    record = records[0]
    assert record.customer == "联创"
    assert record.product == "G30A"
    assert [item.amount_raw for item in record.materials] == [
        "55", "35-36", "2（加到3%）"
    ]
    assert record.notes_raw == "客户要求保持黑度"


def test_rejects_failed_formula_but_keeps_classified_terms():
    sheet = sheet_from_rows(
        "G30A",
        [["配方（作废）", "PA6", "玻纤"], [None, "55", "35"]],
    )
    result = extract_sheet(sheet, customer_hint="联创")
    assert result.formulas == []
    assert {term.value for term in result.lexicon_terms} >= {"G30A", "PA6", "玻纤"}
    assert result.exclusions[0].reason == "INVALID_FORMULA"
```

Also cover unknown dates, stacked blocks, source-order anchoring, title/sheet
conflicts, sparse cells, notes without process rows, and explicit units kept inside
`amount_raw`.

- [ ] **Step 2: Witness red**

Run `python -m pytest tests_lite/test_formula_extractor.py -q`.

- [ ] **Step 3: Implement a state-machine extractor**

The extractor locates `配方` anchors, bounds each block at the next anchor/title,
pairs the following amount row by column, identifies optional `工艺` and note rows,
and emits immutable `FormulaCandidate` records. It never repairs material names or
amounts. Confidence is based on structural evidence, not model inference.

- [ ] **Step 4: Run extraction tests green**

Expected: all grammar tests pass without snapshots containing private data.

### Task 4: Evidence rendering and deterministic dedupe

**Files:**
- Create: `lite_app/knowledge/evidence_renderer.py`
- Modify: `lite_app/knowledge/import_models.py`
- Create: `tests_lite/test_import_evidence.py`

- [ ] **Step 1: Write failing tests**

Assert that a formula candidate produces:

- a stable SHA-256 content fingerprint;
- a tight PNG containing its exact rows and columns;
- a context PNG with one title/date row above and one note row below;
- no path derived directly from workbook text.

- [ ] **Step 2: Witness red**

Run `python -m pytest tests_lite/test_import_evidence.py -q`.

- [ ] **Step 3: Implement**

Render cells to a Pillow canvas using a bundled CJK-capable font fallback. Name
evidence files with the content fingerprint. Deduplicate only when customer,
product, normalized date and normalized structural content match; merge provenance
arrays without discarding source locations.

- [ ] **Step 4: Run green**

Expected: PNG dimensions are positive, fingerprints are stable, and distinct dates
remain distinct.

### Task 5: Database staging and import transaction

**Files:**
- Modify: `lite_app/knowledge/migrations.py`
- Create: `lite_app/knowledge/import_service.py`
- Create: `tests_lite/test_personal_import.py`

- [ ] **Step 1: Write failing migration/import tests**

Test a temporary SQLite database:

```python
summary = service.import_candidates(candidates, source_run_id="run-1")
assert summary.formulas_imported == 1
assert summary.formulas_pending == 1
assert summary.lexicon_terms_imported >= 3
assert db.count("formulas") == 1
assert db.count("import_candidates", status="PENDING_REVIEW") == 1
```

Repeat the same import and assert idempotency plus merged provenance.

- [ ] **Step 2: Witness red**

Run `python -m pytest tests_lite/test_personal_import.py -q`.

- [ ] **Step 3: Add migration and transactional service**

Add source-order, unknown-date, notes, source, evidence, staging and exclusion tables.
Back up the target database before the transaction. Roll back formulas, lexicon and
provenance together on any failure.

- [ ] **Step 4: Run green**

Expected: idempotent import, durable pending records, and no partial write on a
forced exception.

### Task 6: AI ZIP protocol

**Files:**
- Create: `lite_app/knowledge/package.py`
- Create: `config/schema/knowledge-package-v1.schema.json`
- Create: `tests_lite/test_knowledge_package.py`

- [ ] **Step 1: Write failing package security tests**

Cover valid package, missing evidence, checksum mismatch, undeclared file, duplicate
manifest path, absolute path, `../` traversal, symlink member, invalid JSONL, invalid
formula marker and amount normalization.

- [ ] **Step 2: Witness red**

Run `python -m pytest tests_lite/test_knowledge_package.py -q`.

- [ ] **Step 3: Implement fail-closed validation**

Parse ZIP metadata before extraction, reject unsafe paths and links, stream each
declared member through SHA-256, validate every JSONL record, and return an immutable
preview. Do not write the database until `commit_preview(preview_id)` is called.

- [ ] **Step 4: Run green**

Expected: valid package previews; every unsafe package is rejected before extraction.

### Task 7: CLI, GitHub AI guide, and real personal extraction

**Files:**
- Create: `scripts/import_personal_history.py`
- Create: `docs/AI_KNOWLEDGE_PACKAGE.md`
- Modify: `README.md`
- Create: `tests_lite/test_import_personal_history_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Test `scan`, `stage`, `validate`, `import`, and `report` subcommands against temporary
fixtures. `scan` must never mutate the database; `import` must require an explicit
validated staging directory.

- [ ] **Step 2: Witness red**

Run `python -m pytest tests_lite/test_import_personal_history_cli.py -q`.

- [ ] **Step 3: Implement CLI and documentation**

Document the exact AI prompt, ZIP tree, schemas, prohibited guessing, exclusion
rules, checksum command, validator command, and import Gate. Add a README link.

- [ ] **Step 4: Run focused and full green**

Run:

```powershell
python -m pytest tests_lite/test_source_scanner.py `
  tests_lite/test_workbook_reader.py `
  tests_lite/test_formula_extractor.py `
  tests_lite/test_import_evidence.py `
  tests_lite/test_personal_import.py `
  tests_lite/test_knowledge_package.py `
  tests_lite/test_import_personal_history_cli.py -q
python -m pytest -m "not real_ocr" -q
python -m ruff check .
git diff --check
```

- [ ] **Step 5: Run the real read-only scan and staged extraction**

Run against `C:\Users\97020\Downloads\各个单位`, inspect aggregate statistics and
bounded samples only, then create the personal database and evidence bundle in an
ignored private build directory. Verify source hashes before and after are identical.
