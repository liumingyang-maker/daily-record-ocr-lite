# Evidence-First Product Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the developer-facing field review UI with an evidence-first customer/product/formula workflow whose confirmed `FinalResult` is transactionally appended to a dated knowledge history and remains the only Excel source.

**Architecture:** Keep FastAPI/Jinja/vanilla JavaScript, but move presentation, review editing, confirmation state, and knowledge history into focused services. All business edits mutate canonical `review/final_result.json`; formula confirmation records content hashes, and finalization writes knowledge plus a matching receipt before READY. Existing field APIs and source install paths remain compatible.

**Tech Stack:** Python 3.11, FastAPI, Jinja2, vanilla JavaScript/CSS, SQLite, openpyxl, pytest, Ruff.

---

## Working conventions

- Work only in `C:\Users\97020\.config\superpowers\worktrees\daily-record-ocr-lite\evidence-first-product-workflow`.
- Use `C:\Users\97020\Desktop\daily-record-ocr-lite\.venv\Scripts\python.exe` for tests and Ruff; do not modify the detached runtime checkout.
- Never read, copy, stage, or report contents from `data/secrets.env`, user jobs, or raw model responses.
- Each task starts red, turns green, runs its focused regression set, and commits only its listed files.

## File map

- `lite_app/presentation.py`: user-facing labels, job summaries, progress and actionable errors.
- `lite_app/upload_options.py`: validated per-image rotations and backward-compatible lookup.
- `lite_app/review_view.py`: read-only evidence-first review view model.
- `lite_app/review_editor.py`: versioned structural edits to canonical `FinalResult`.
- `lite_app/review_state.py`: formula content hashes, confirmations and finalization receipt.
- `lite_app/knowledge/migrations.py`: non-destructive, backed-up SQLite schema migrations.
- `lite_app/knowledge/history.py`: transactional append/query/revision operations.
- `lite_app/knowledge/exporter.py`: knowledge timeline Excel export.
- `lite_app/static/upload.js`: preview, reorder, rotate and remove uploads.
- `lite_app/static/review.js`: autosave, formula/material/process operations and confirmations.
- `lite_app/static/knowledge.js`: customer/product timeline navigation and comparison.
- Existing `lite_app/main.py`: thin HTTP routes and compatibility redirects only.

### Task 1: User-facing status, navigation, and recognition records

**Files:**
- Create: `lite_app/presentation.py`
- Create: `lite_app/templates/jobs.html`
- Modify: `lite_app/templates/base.html`
- Modify: `lite_app/templates/index.html`
- Modify: `lite_app/main.py`
- Create: `tests_lite/test_user_pages.py`

- [ ] **Step 1: Write failing page and presenter tests**

```python
from lite_app.presentation import present_job, user_status


def test_internal_statuses_have_user_language():
    assert user_status("REVIEW_REQUIRED")["label"] == "需要确认"
    assert user_status("FAILED_SCHEMA")["label"] == "识别失败"


def test_job_summary_prefers_business_identity():
    summary = present_job({
        "id": "20260727-000000-abcdef",
        "status": "REVIEW_REQUIRED",
        "created_at": "2026-07-27T00:00:00",
        "images": [{}, {}],
        "business_summary": {
            "customers": ["联创"],
            "products": ["G30A"],
            "date_min": "2026-07-01",
            "date_max": "2026-07-26",
        },
    })
    assert summary["customer"] == "联创"
    assert summary["product"] == "G30A"
    assert summary["next_action"] == "继续确认"
```

Add TestClient assertions that `/` links to “开始识别 / 识别记录 / 配方知识库 / 设置”, `/jobs` exists, and normal list headers do not contain `Provider / Model`.

- [ ] **Step 2: Run the tests and verify red**

Run:

```powershell
& 'C:\Users\97020\Desktop\daily-record-ocr-lite\.venv\Scripts\python.exe' -m pytest tests_lite/test_user_pages.py -q
```

Expected: collection fails because `lite_app.presentation` and `/jobs` do not exist.

- [ ] **Step 3: Implement the presenter and routes**

```python
_STATUS = {
    "UPLOADED": ("正在识别", "查看进度", "working"),
    "PREPROCESSING": ("正在识别", "查看进度", "working"),
    "OCR_RUNNING": ("正在识别", "查看进度", "working"),
    "VISION_RUNNING": ("正在识别", "查看进度", "working"),
    "MATCHING_HISTORY": ("正在整理配方", "查看进度", "working"),
    "FUSING": ("正在整理配方", "查看进度", "working"),
    "REVIEW_REQUIRED": ("需要确认", "继续确认", "review"),
    "READY": ("可以导出", "导出 Excel", "ready"),
    "EXPORTING": ("正在生成 Excel", "查看进度", "working"),
    "EXPORTED": ("已完成", "查看记录", "done"),
    "FAILED": ("识别失败", "查看原因并重试", "failed"),
    "FAILED_SCHEMA": ("识别失败", "查看原因并重试", "failed"),
    "DEGRADED": ("识别失败", "查看原因并重试", "failed"),
}


def user_status(status: str) -> dict[str, str]:
    label, action, tone = _STATUS.get(status, ("正在整理", "查看详情", "working"))
    return {"label": label, "action": action, "tone": tone}
```

`present_job()` must fall back to “正在整理” rather than `- / -`, expose a four-step progress state for image processing, handwriting reading, formula organization and user confirmation, and keep job ID/provider/model only in an `advanced` mapping. The page route loads `business_entities.json` when present and derives customer/product/date summaries without changing the job file. Render recent five records on `/`; render up to all stored records on `/jobs`.

- [ ] **Step 4: Run focused and existing web tests**

Run:

```powershell
& 'C:\Users\97020\Desktop\daily-record-ocr-lite\.venv\Scripts\python.exe' -m pytest tests_lite/test_user_pages.py tests_lite/test_web.py tests_lite/test_v1_web_contract.py -q
```

Expected: PASS; existing URLs and setup gating remain intact.

- [ ] **Step 5: Commit**

```powershell
git add lite_app/presentation.py lite_app/templates/base.html lite_app/templates/index.html lite_app/templates/jobs.html lite_app/main.py tests_lite/test_user_pages.py
git commit -m "feat: present recognition records in user language"
```

### Task 2: Per-image upload preview, ordering, and rotation

**Files:**
- Create: `lite_app/upload_options.py`
- Create: `lite_app/static/upload.js`
- Modify: `lite_app/templates/index.html`
- Modify: `lite_app/main.py`
- Modify: `lite_app/storage.py`
- Modify: `lite_app/pipeline_v2.py`
- Modify: `tests_lite/test_web.py`
- Modify: `tests_lite/test_storage.py`
- Create: `tests_lite/test_upload_options.py`

- [ ] **Step 1: Write failing rotation contract tests**

```python
import pytest

from lite_app.upload_options import normalize_rotations, rotation_for_image


def test_per_image_rotations_are_validated_and_addressed_by_index():
    rotations = normalize_rotations('["90cw", "auto"]', count=2, fallback="auto")
    job = {"rotation": "auto", "rotations": rotations}
    assert rotation_for_image(job, 1) == "90cw"
    assert rotation_for_image(job, 2) == "auto"


def test_rotation_count_must_match_images():
    with pytest.raises(ValueError, match="图片数量"):
        normalize_rotations('["auto"]', count=2, fallback="auto")


def test_legacy_job_keeps_single_rotation():
    assert rotation_for_image({"rotation": "180"}, 3) == "180"
```

Extend the upload API test to submit `rotation_manifest='["90cw","0"]'` and assert the stored job has that ordered list.

- [ ] **Step 2: Run the tests and verify red**

Run:

```powershell
& 'C:\Users\97020\Desktop\daily-record-ocr-lite\.venv\Scripts\python.exe' -m pytest tests_lite/test_upload_options.py tests_lite/test_web.py -q
```

Expected: FAIL because the manifest is ignored.

- [ ] **Step 3: Implement server-side manifest handling**

```python
VALID_ROTATIONS = {"auto", "0", "90cw", "90ccw", "180"}


def normalize_rotations(raw: str, *, count: int, fallback: str) -> list[str]:
    values = json.loads(raw) if raw.strip() else [fallback] * count
    if not isinstance(values, list) or len(values) != count:
        raise ValueError("旋转设置与图片数量不一致")
    normalized = [str(value) for value in values]
    if any(value not in VALID_ROTATIONS for value in normalized):
        raise ValueError("旋转设置包含无效值")
    return normalized


def rotation_for_image(job: dict, one_based_index: int) -> str:
    values = job.get("rotations")
    if isinstance(values, list) and one_based_index <= len(values):
        return str(values[one_based_index - 1])
    return str(job.get("rotation", "auto"))
```

Parse the manifest only after all files validate, persist it through `JobStorage.create_job(rotations=...)`, use `rotation_for_image()` in preprocessing and OCR cache keys, and redirect new jobs to `/jobs/{id}`.

- [ ] **Step 4: Implement the upload preview**

`upload.js` maintains ordered `{file, rotation, objectUrl}` entries, renders thumbnails with “左转 / 右转 / 上移 / 下移 / 删除”, rebuilds the native `FileList` with `DataTransfer` before submission, and writes the ordered rotation array to a hidden `rotation_manifest` input. Revoke every object URL when an item is removed or the page unloads.

- [ ] **Step 5: Run focused tests and Ruff**

Run:

```powershell
& 'C:\Users\97020\Desktop\daily-record-ocr-lite\.venv\Scripts\python.exe' -m pytest tests_lite/test_upload_options.py tests_lite/test_storage.py tests_lite/test_web.py -q
& 'C:\Users\97020\Desktop\daily-record-ocr-lite\.venv\Scripts\python.exe' -m ruff check lite_app tests_lite
```

Expected: all commands PASS.

- [ ] **Step 6: Commit**

```powershell
git add lite_app/upload_options.py lite_app/static/upload.js lite_app/templates/index.html lite_app/main.py lite_app/storage.py lite_app/pipeline_v2.py tests_lite/test_upload_options.py tests_lite/test_storage.py tests_lite/test_web.py
git commit -m "feat: support ordered per-image upload controls"
```

### Task 3: Evidence-first review view model

**Files:**
- Create: `lite_app/review_view.py`
- Create: `tests_lite/review_fixtures.py`
- Create: `tests_lite/test_review_view.py`

- [ ] **Step 1: Add a reusable strict review fixture**

Create `make_review_final(job_id)` by loading `config/mock_result.json`, assigning stable formula IDs, projecting with `project_final_result()`, and setting exactly one amount field to `CONFLICT`, one date to empty, and all other required fields to `AUTO_ACCEPT`. The helper must return only synthetic data and never read `data/`.

- [ ] **Step 2: Write failing view-model tests**

```python
from lite_app.review_view import build_review_view
from tests_lite.review_fixtures import make_review_final


def test_review_view_groups_by_customer_product_and_prioritizes_issues():
    view = build_review_view(
        {"id": "job-review", "status": "REVIEW_REQUIRED", "images": [{"source": "source/a.jpg"}]},
        make_review_final("job-review"),
        confirmed={},
    )
    formula = view["groups"][0]["formulas"][0]
    assert view["summary"]["needs_confirmation"] == 1
    assert formula["needs_confirmation"] is True
    assert formula["evidence"]["image_url"].endswith("source/a.jpg")
    assert "field_id" not in formula["materials"][0]
    assert formula["materials"][0]["amount"]["needs_confirmation"] is True
```

Also assert the blocking message is `待确认：联创 / G30A / 配方1 缺少日期` and that candidates, OCR/VLM labels and BBox are not exposed as visible labels.

- [ ] **Step 3: Run the tests and verify red**

Run:

```powershell
& 'C:\Users\97020\Desktop\daily-record-ocr-lite\.venv\Scripts\python.exe' -m pytest tests_lite/test_review_view.py -q
```

Expected: FAIL because the view builder is absent.

- [ ] **Step 4: Implement the read-only view builder**

```python
REVIEW_STATUSES = {"CONFLICT", "EMPTY", "NEED_REVIEW"}


def present_field(field: dict, *, required: bool) -> dict:
    value = str(field.get("value", ""))
    status = str(field.get("status", field.get("review_status", "NEED_REVIEW")))
    return {
        "value": value,
        "needs_confirmation": status in REVIEW_STATUSES or (required and not value.strip()),
        "confidence": float(field.get("confidence", 0.0)),
    }
```

`build_review_view()` must group page company plus product section, include opaque IDs only as `id` properties used by API calls, map image index to the existing secure file URL, include normalized evidence rectangles for rendering, order problem formulas first, and return advanced technical metadata separately.

- [ ] **Step 5: Run focused tests**

Run:

```powershell
& 'C:\Users\97020\Desktop\daily-record-ocr-lite\.venv\Scripts\python.exe' -m pytest tests_lite/test_review_view.py tests_lite/test_v1_contracts.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add lite_app/review_view.py tests_lite/review_fixtures.py tests_lite/test_review_view.py
git commit -m "feat: build evidence-first review view model"
```

### Task 4: Versioned canonical FinalResult editor

**Files:**
- Create: `lite_app/review_editor.py`
- Modify: `lite_app/final_result.py`
- Create: `tests_lite/test_review_editor.py`

- [ ] **Step 1: Write failing structural-edit tests**

Cover all required operations in separate tests:

```python
editor.update_identity(group_id, customer="联创", product="G30A", expected_version=version)
formula_id = editor.add_formula(group_id, expected_version=next_version)
material_id = editor.add_material(formula_id, {"name": "PA66", "amount": "60", "unit": "kg"}, expected_version=version)
editor.update_material(formula_id, material_id, {"amount": "62"}, expected_version=version)
editor.reorder_materials(formula_id, [material_id, existing_id], expected_version=version)
parameter_id = editor.add_process_parameter(formula_id, {"name": "温度", "value": "260", "unit": "℃"}, expected_version=version)
editor.delete_process_parameter(formula_id, parameter_id, expected_version=version)
editor.delete_material(formula_id, material_id, expected_version=version)
editor.delete_formula(formula_id, expected_version=version)
```

After every operation, reload through `FinalResultService` and validate with `validate_final_result_contract()`. Add a stale-version test expecting `ReviewVersionConflict` and an undo test restoring the last deleted material.

- [ ] **Step 2: Run the tests and verify red**

Run:

```powershell
& 'C:\Users\97020\Desktop\daily-record-ocr-lite\.venv\Scripts\python.exe' -m pytest tests_lite/test_review_editor.py -q
```

Expected: FAIL because structural edits do not exist.

- [ ] **Step 3: Add one atomic mutation primitive**

```python
def mutate(self, expected_version: str, callback: Callable[[dict], Any]) -> tuple[Any, dict]:
    final = self.load()
    if str(final.get("updated_at", "")) != expected_version:
        raise FinalResultError("结果已在另一个窗口更新，请刷新后重试")
    result = callback(final)
    final["updated_at"] = _now()
    final["summary"] = summarize_final_result(final)
    self.save(final)
    self._project_business_entities(final)
    return result, final
```

`ReviewEditor.__init__(job_dir)` owns one `FinalResultService`; `ReviewEditor.load()` returns that service's current result. Every mutation uses the primitive above, generates collision-resistant IDs, creates complete schema-valid manual evidence fields, appends a local correction record, and writes a one-level deletion snapshot to `review/undo.json`. Export `find_identity_and_formula(final, formula_id)` as the single lookup used by the editor, confirmation hash and view builder. No editor method may write only `business_entities.json`.

- [ ] **Step 4: Implement editor validation**

Use explicit resource lookup helpers and reject unknown keys. `record_date` accepts only ISO `YYYY-MM-DD`; formula sequence and material order are recomputed after add/delete/reorder. Identity edits update page company and section product fields in `FinalResult`, marking them manually confirmed.

- [ ] **Step 5: Run focused and schema tests**

Run:

```powershell
& 'C:\Users\97020\Desktop\daily-record-ocr-lite\.venv\Scripts\python.exe' -m pytest tests_lite/test_review_editor.py tests_lite/test_v1_contracts.py tests_lite/test_readiness.py -q
```

Expected: PASS; every saved result remains record-v1 valid.

- [ ] **Step 6: Commit**

```powershell
git add lite_app/review_editor.py lite_app/final_result.py tests_lite/test_review_editor.py
git commit -m "feat: edit canonical formula structures"
```

### Task 5: Whole-formula confirmation and unified review page

**Files:**
- Create: `lite_app/review_state.py`
- Create: `lite_app/static/review.js`
- Replace: `lite_app/templates/job.html`
- Modify: `lite_app/static/style.css`
- Modify: `lite_app/main.py`
- Create: `tests_lite/test_review_state.py`
- Create: `tests_lite/test_review_api.py`
- Modify: `tests_lite/test_v1_web_contract.py`

- [ ] **Step 1: Write failing confirmation-state tests**

```python
def test_formula_confirmation_marks_visible_values_and_records_hash(tmp_path):
    store = ReviewStateStore(tmp_path)
    editor = ReviewEditor(tmp_path)
    result = confirm_formula(editor, store, formula_id, expected_version)
    assert result["confirmed"] is True
    assert store.is_confirmed(editor.load(), formula_id) is True


def test_edit_invalidates_confirmation(tmp_path):
    store.confirm(final, formula_id)
    editor.update_formula(formula_id, {"record_date": "2026-07-27"}, final["updated_at"])
    assert store.is_confirmed(editor.load(), formula_id) is False
```

Add failures for missing customer, product, date, material name and material amount. Required-empty values must not become `MANUAL_CONFIRMED_EMPTY`; optional empty unit, notes and process unit may.

- [ ] **Step 2: Run the tests and verify red**

Run:

```powershell
& 'C:\Users\97020\Desktop\daily-record-ocr-lite\.venv\Scripts\python.exe' -m pytest tests_lite/test_review_state.py tests_lite/test_review_api.py -q
```

Expected: FAIL because confirmation storage and business routes are missing.

- [ ] **Step 3: Implement deterministic confirmation hashes**

```python
def formula_content_hash(final: dict, formula_id: str) -> str:
    identity, formula = find_identity_and_formula(final, formula_id)
    payload = {"customer": identity.customer, "product": identity.product, "formula": formula}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

Store `review/review_state.json` as schema-versioned JSON with `confirmed_formulas`. Confirmation validates business requirements, marks unresolved non-empty fields `MANUAL_CONFIRMED`, optional empty fields `MANUAL_CONFIRMED_EMPTY`, saves `FinalResult`, then records the post-save hash.

- [ ] **Step 4: Add business APIs and compatibility redirect**

Implement JSON-only local-write routes for review GET, identity/formula/material/process CRUD/reorder, undo and formula confirm. Return `{version, saved, confirmed, message}` in user language. Formula deletion requires an explicit `confirmed: true` request flag; material and process deletion return an undo token consumed by the undo route. Do not expose the finalization route or button until Task 6. Change `/jobs/{id}/result` to 303 redirect to `/jobs/{id}#review`; keep old field APIs.

- [ ] **Step 5: Replace the developer table with formula cards**

The new template renders summary and empty shells only; `review.js` loads the view model, shows issues first, toggles all formulas, renders evidence next to editable values, debounces autosave, provides add/delete/reorder/undo, confirms one formula, and exposes advanced diagnostics in a collapsed `<details>`. Escape all values with DOM `textContent`; never interpolate recognized text into `innerHTML`.

- [ ] **Step 6: Run focused browser-contract tests**

Run:

```powershell
& 'C:\Users\97020\Desktop\daily-record-ocr-lite\.venv\Scripts\python.exe' -m pytest tests_lite/test_review_state.py tests_lite/test_review_api.py tests_lite/test_user_pages.py tests_lite/test_v1_web_contract.py -q
```

Expected: PASS; `/jobs/{id}` contains “确认这条配方” and does not render `字段ID`, `VLM`, `BBox`, or `确认所有字段`.

- [ ] **Step 7: Commit**

```powershell
git add lite_app/review_state.py lite_app/static/review.js lite_app/templates/job.html lite_app/static/style.css lite_app/main.py tests_lite/test_review_state.py tests_lite/test_review_api.py tests_lite/test_v1_web_contract.py
git commit -m "feat: add whole-formula evidence review workspace"
```

### Task 6: Transactional dated knowledge history and READY receipt

**Files:**
- Create: `lite_app/knowledge/migrations.py`
- Create: `lite_app/knowledge/history.py`
- Modify: `lite_app/knowledge/database.py`
- Modify: `lite_app/readiness.py`
- Modify: `lite_app/main.py`
- Create: `tests_lite/test_knowledge_migrations.py`
- Create: `tests_lite/test_knowledge_history.py`
- Modify: `tests_lite/test_readiness.py`

- [ ] **Step 1: Write failing non-destructive migration tests**

Create a v1 database with one material and one legacy formula, run `KnowledgeDB.initialize()`, and assert:

```python
assert backup_path.exists()
assert legacy_formula["title"] == "旧配方"
assert migrated_columns >= {
    "formula_no", "record_date", "confirmed_at", "source_job_id",
    "source_formula_id", "source_image_index", "revision_of_id",
}
assert "formula_process_parameters" in table_names
```

Run initialization twice and assert it is idempotent and creates no second migration backup.

- [ ] **Step 2: Write failing transaction, history, and receipt tests**

```python
receipt = history.append_confirmed_job(job, final, confirmed_hashes)
assert receipt["final_result_sha256"] == final_result_fingerprint(final)
assert history.timeline("联创", "G30A")[0]["record_date"] == "2026-07-27"
assert history.append_confirmed_job(job, final, confirmed_hashes) == receipt
```

Add tests that a second date appends, a write failure rolls back all rows, same source job/formula is idempotent, and a revision inserts a linked row rather than updating history.

- [ ] **Step 3: Run the tests and verify red**

Run:

```powershell
& 'C:\Users\97020\Desktop\daily-record-ocr-lite\.venv\Scripts\python.exe' -m pytest tests_lite/test_knowledge_migrations.py tests_lite/test_knowledge_history.py -q
```

Expected: FAIL because v2 history columns and transaction service do not exist.

- [ ] **Step 4: Implement backed-up migrations**

`apply_migrations(connection, db_path)` creates `schema_migrations`, copies the closed database to `backups/knowledge-before-v2-<timestamp>.sqlite3` before the first v2 migration, adds nullable columns without rebuilding existing tables, creates `formula_process_parameters`, and creates a partial unique index on `(source_job_id, source_formula_id)` where both values are non-null.

- [ ] **Step 5: Implement one-transaction append**

`KnowledgeHistory.append_confirmed_job()` starts `BEGIN IMMEDIATE`, selects-or-inserts customer and customer-scoped product, inserts formula/items/process rows, commits once, and rolls back on every exception. It accepts only a fully confirmed, valid `FinalResult`; every formula hash must match `ReviewStateStore`, and it never calls existing per-row methods that commit independently.

- [ ] **Step 6: Split content-ready from final READY**

Add `evaluate_content_gate()` for schema, fields, engines and projections. `evaluate_ready_gate()` calls it and additionally requires `review/finalization.json` whose final hash matches the current `FinalResult`. The finalize API runs the content gate, appends knowledge, writes the receipt atomically, reevaluates READY, and only then saves job status. Existing `/api/jobs/{id}/confirm` becomes a compatibility alias for finalize.

- [ ] **Step 7: Run focused tests**

Run:

```powershell
& 'C:\Users\97020\Desktop\daily-record-ocr-lite\.venv\Scripts\python.exe' -m pytest tests_lite/test_knowledge_migrations.py tests_lite/test_knowledge_history.py tests_lite/test_readiness.py tests_lite/test_review_api.py tests_lite/test_exporter.py -q
```

Expected: PASS; Excel remains blocked before receipt and allowed after finalization.

- [ ] **Step 8: Commit**

```powershell
git add lite_app/knowledge/migrations.py lite_app/knowledge/history.py lite_app/knowledge/database.py lite_app/readiness.py lite_app/main.py tests_lite/test_knowledge_migrations.py tests_lite/test_knowledge_history.py tests_lite/test_readiness.py tests_lite/test_review_api.py
git commit -m "feat: append confirmed formulas to dated knowledge history"
```

### Task 7: Customer/product/date knowledge browser

**Files:**
- Create: `lite_app/knowledge/exporter.py`
- Create: `lite_app/static/knowledge.js`
- Replace: `lite_app/templates/knowledge.html`
- Modify: `lite_app/static/style.css`
- Modify: `lite_app/main.py`
- Create: `tests_lite/test_knowledge_pages.py`
- Create: `tests_lite/test_knowledge_exporter.py`

- [ ] **Step 1: Write failing tree, detail, compare, and export tests**

Seed two dated formulas under `联创 / G30A`, then assert:

```python
tree = client.get("/api/knowledge/tree?q=G30A").json()
assert tree["customers"][0]["products"][0]["formula_count"] == 2
detail = client.get(f"/api/knowledge/formulas/{formula_id}").json()
assert detail["record_date"] == "2026-07-27"
comparison = client.get(f"/api/knowledge/compare?left={older}&right={newer}").json()
assert comparison["materials"]["PA66"]["before"] == "60"
assert comparison["materials"]["PA66"]["after"] == "62"
```

Load the exported workbook and assert chronological rows and customer/product/date columns.

- [ ] **Step 2: Run the tests and verify red**

Run:

```powershell
& 'C:\Users\97020\Desktop\daily-record-ocr-lite\.venv\Scripts\python.exe' -m pytest tests_lite/test_knowledge_pages.py tests_lite/test_knowledge_exporter.py -q
```

Expected: FAIL because history endpoints are absent.

- [ ] **Step 3: Implement read and export services**

Add parameterized SQLite queries only. Tree search matches customer, product or date; formula detail returns materials, process values and a secure source-job image URL; comparison aligns material and process names without mutating either record. Excel export orders by `record_date, confirmed_at, id` and applies existing Excel formula-safety sanitization.

- [ ] **Step 4: Build the knowledge interface**

Default view is customer → product → date timeline. Selecting a date loads formula details and evidence; selecting two dates enables “比较配方”. Legacy formulas with no migrated date remain visible as “历史数据未记录日期”. Move material add/import/list into a collapsed “物料字典” section. Empty and error states use user language and retain retry/search actions.

- [ ] **Step 5: Run focused tests**

Run:

```powershell
& 'C:\Users\97020\Desktop\daily-record-ocr-lite\.venv\Scripts\python.exe' -m pytest tests_lite/test_knowledge_pages.py tests_lite/test_knowledge_exporter.py tests_lite/test_knowledge_history.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add lite_app/knowledge/exporter.py lite_app/static/knowledge.js lite_app/templates/knowledge.html lite_app/static/style.css lite_app/main.py tests_lite/test_knowledge_pages.py tests_lite/test_knowledge_exporter.py
git commit -m "feat: browse dated customer product knowledge"
```

### Task 8: Progressive-disclosure settings, setup, and global error UX

**Files:**
- Create: `lite_app/static/settings.js`
- Modify: `lite_app/templates/settings.html`
- Modify: `lite_app/templates/setup.html`
- Modify: `lite_app/templates/base.html`
- Modify: `lite_app/static/style.css`
- Modify: `lite_app/presentation.py`
- Modify: `tests_lite/test_user_pages.py`
- Modify: `tests_lite/test_v1_web_contract.py`

- [ ] **Step 1: Write failing normal-user-content tests**

Assert default settings HTML contains “AI识别服务 / 当前模型 / 测试连接 / OCR引擎 / 运行系统检查”, has one closed `<details>` named “高级设置”, and does not show raw JSON in a `<pre>` before a test runs. Assert setup headings are Chinese and do not display `Step`, `Preset`, `tier`, or `Device` outside the advanced section.

- [ ] **Step 2: Run the tests and verify red**

Run:

```powershell
& 'C:\Users\97020\Desktop\daily-record-ocr-lite\.venv\Scripts\python.exe' -m pytest tests_lite/test_user_pages.py tests_lite/test_v1_web_contract.py -q
```

Expected: FAIL against current developer-facing labels.

- [ ] **Step 3: Implement progressive disclosure**

`settings.js` maps connection results to concise cards, keeps the existing three Qwen capability booleans inside “复制诊断信息”, writes copied JSON through `textContent`, and never includes secrets. Provider/Base URL/Endpoint/device/threshold remain editable under advanced settings. Setup uses five Chinese stages and retains the real OCR plus real vision Gate.

- [ ] **Step 4: Add actionable error presentation**

Map transport, authentication, timeout, schema and provider errors to a user message plus next action; keep HTTP status/request ID in advanced diagnostics. Add visible focus states, non-color status icons, mobile card stacking, and one solid primary action per page.

- [ ] **Step 5: Run page, settings, and secret-safety tests**

Run:

```powershell
& 'C:\Users\97020\Desktop\daily-record-ocr-lite\.venv\Scripts\python.exe' -m pytest tests_lite/test_user_pages.py tests_lite/test_v1_web_contract.py tests_lite/test_configure_cli.py -q
```

Expected: PASS and no secret value appears in responses.

- [ ] **Step 6: Commit**

```powershell
git add lite_app/static/settings.js lite_app/templates/settings.html lite_app/templates/setup.html lite_app/templates/base.html lite_app/static/style.css lite_app/presentation.py tests_lite/test_user_pages.py tests_lite/test_v1_web_contract.py
git commit -m "feat: simplify setup and diagnostics for users"
```

### Task 9: Full workflow and backward-compatibility regression

**Files:**
- Create: `tests_lite/test_user_workflow_e2e.py`
- Modify: `tests_lite/test_pipeline_v2_e2e.py`
- Modify: `tests_lite/test_exporter.py`
- Modify: `docs/DATA_AND_PRIVACY.md`
- Modify: `README.md`

- [ ] **Step 1: Write the full failing user-journey test**

The TestClient journey must:

1. Create a two-image job with separate rotations.
2. Install a synthetic valid `FinalResult` containing two formulas.
3. Load review and see only the problem formula expanded.
4. Fill customer, product and both ISO dates.
5. Edit, add, reorder and delete material/process rows.
6. Confirm each formula.
7. Finalize and assert READY plus a knowledge receipt.
8. Query the customer/product timeline and compare both dates.
9. Export Excel and assert its cells match the edited `FinalResult`.
10. Re-finalize and assert no duplicate knowledge rows.

- [ ] **Step 2: Run the complete journey and require green**

Run:

```powershell
& 'C:\Users\97020\Desktop\daily-record-ocr-lite\.venv\Scripts\python.exe' -m pytest tests_lite/test_user_workflow_e2e.py -q
```

Expected: PASS. If it fails, add the smallest failing assertion to the focused test file for the responsible service from Tasks 2-7, fix that service, rerun its focused suite, and rerun this journey before continuing.

- [ ] **Step 3: Update user and privacy documentation**

Update README with the exact user flow, append-only history semantics, latest stable update guidance, and the distinction between source updates and the separately specified desktop installers. Update privacy docs with knowledge evidence references, local data retention and explicit deletion rules.

- [ ] **Step 4: Run all source gates**

Run:

```powershell
& 'C:\Users\97020\Desktop\daily-record-ocr-lite\.venv\Scripts\python.exe' -m pytest -m "not real_ocr" -q
& 'C:\Users\97020\Desktop\daily-record-ocr-lite\.venv\Scripts\python.exe' -m ruff check lite_app tests_lite scripts
& 'C:\Users\97020\Desktop\daily-record-ocr-lite\.venv\Scripts\python.exe' -m pytest -m real_ocr -q -s
& 'C:\Users\97020\Desktop\daily-record-ocr-lite\.venv\Scripts\python.exe' scripts/doctor.py --json
git diff --check
```

Expected: ordinary tests PASS; Ruff prints `All checks passed!`; at least one real OCR test passes rather than all being skipped; doctor is not `BROKEN`; diff check emits no output.

- [ ] **Step 5: Run secret and private-artifact checks**

Run:

```powershell
git grep -n -E 'sk-(ws|sp)-[A-Za-z0-9._-]+'
git diff --cached | Select-String -Pattern 'sk-(ws|sp)-[A-Za-z0-9._-]+'
git status --short
```

Expected: no key matches; status contains no `data/`, logs, raw responses, images, generated Excel files, or SQLite databases.

- [ ] **Step 6: Commit**

```powershell
git add tests_lite/test_user_workflow_e2e.py tests_lite/test_pipeline_v2_e2e.py tests_lite/test_exporter.py docs/DATA_AND_PRIVACY.md README.md
git commit -m "test: verify evidence-first user workflow"
```

### Task 10: Visual verification, audit report, and Draft PR handoff

**Files:**
- Create: `docs/audits/EVIDENCE_FIRST_PRODUCT_WORKFLOW_AUDIT.md`
- Modify only if a verified defect is found: files already listed in Tasks 1-9

- [ ] **Step 1: Start the isolated application with synthetic/private-safe data**

Run the app against a temporary data directory and a non-production port. Do not point the isolated branch at the user’s existing `data/`.

- [ ] **Step 2: Verify the actual pages in a browser**

Check desktop and narrow viewport for `/`, `/jobs`, one processing job, one review job, `/knowledge`, `/settings`, and `/setup`. Verify keyboard focus, one primary CTA, evidence/form alignment, default problem-only behavior, add/delete/undo, confirmation, knowledge timeline and error/empty/loading states. Then run one new real-image job using local private settings in a temporary non-repository data location; record only redacted provider/model/status/timings and artifact existence, never the key, image, or full model response.

- [ ] **Step 3: Re-run the final gates after visual fixes**

Run:

```powershell
& 'C:\Users\97020\Desktop\daily-record-ocr-lite\.venv\Scripts\python.exe' -m pytest -m "not real_ocr" -q
& 'C:\Users\97020\Desktop\daily-record-ocr-lite\.venv\Scripts\python.exe' -m ruff check lite_app tests_lite scripts
& 'C:\Users\97020\Desktop\daily-record-ocr-lite\.venv\Scripts\python.exe' -m pytest -m real_ocr -q -s
git diff --check
```

Expected: all green.

- [ ] **Step 4: Write the copyable audit report**

Record branch SHA, base SHA, commit list, changed-file inventory, requirement-to-test evidence, test count, Ruff/diff results, browser scenarios, database migration/rollback evidence, FinalResult/knowledge/Excel lineage, secret scans, known limits, and the explicit statement that desktop installers are tracked by `2026-07-27-desktop-installers-design.md` and not claimed complete here.

- [ ] **Step 5: Commit the audit and request code review**

```powershell
git add docs/audits/EVIDENCE_FIRST_PRODUCT_WORKFLOW_AUDIT.md
git commit -m "docs: audit evidence-first product workflow"
```

Run the requesting-code-review skill, address verified findings with new tests, and repeat all gates.

- [ ] **Step 6: Push and open a Draft PR only**

Push `feat/evidence-first-product-workflow` and create a Draft PR to `master`. Include the audit evidence and state that there is no merge, tag, release, or desktop-package claim until the user separately authorizes those actions and every applicable Gate passes.
