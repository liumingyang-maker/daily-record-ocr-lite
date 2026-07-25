# Qwen3.7 Plus record-v1 Schema Prompt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure the production Qwen3.7 Plus request receives the complete `record-v1` JSON Schema while retaining Alibaba's supported `json_object` request format.

**Architecture:** Extract the `pipeline_v2` business prompt construction into a pure function. Serialize the existing Schema as compact JSON inside the user prompt, then keep all provider request controls and downstream fail-closed validation unchanged.

**Tech Stack:** Python 3.11, FastAPI pipeline, JSON Schema 2020-12, pytest, Ruff.

---

## File structure

- Modify `lite_app/pipeline_v2.py`: add the pure prompt builder and route the production
  Vision call through it.
- Create `tests_lite/test_pipeline_v2_prompt.py`: lock the full Schema, normalized bbox,
  1-based page index, OCR evidence and Layout evidence into the outgoing prompt.
- Update `docs/audits/QWEN_FIVE_MINUTE_TIMEOUT_AUDIT.md`: record the root cause,
  RED/GREEN evidence and the new real Job result without secrets or raw business content.

### Task 1: Lock the missing production contract with a RED test

**Files:**
- Create: `tests_lite/test_pipeline_v2_prompt.py`
- Read: `config/record_schema.yaml`
- Read: `config/schema/record-v1.schema.json`

- [ ] **Step 1: Write the failing prompt-contract test**

```python
import json

from lite_app import pipeline_v2
from lite_app.config import load_schema_config


def test_business_prompt_contains_complete_record_v1_contract() -> None:
    builder = getattr(pipeline_v2, "build_vision_user_prompt", None)
    assert builder is not None, "pipeline_v2 must expose a testable prompt builder"

    schema_config = load_schema_config()
    ocr_evidence = [{"image_index": 1, "ocr_tokens": [{"id": "p1_t001"}]}]
    layout_evidence = {"1": {"lines": [], "pairs": [], "records": []}}

    prompt = builder(schema_config, ocr_evidence, layout_evidence)
    compact_schema = json.dumps(
        schema_config["schema"],
        ensure_ascii=False,
        separators=(",", ":"),
    )

    assert f"JSON_SCHEMA={compact_schema}" in prompt
    assert '"required":["schema_version","pages","warnings"]' in prompt
    assert '"material_id"' in prompt
    assert '"formula_no"' in prompt
    assert '"AUTO_ACCEPT"' in prompt
    assert '"maximum":1' in prompt
    assert "source_image_index 必须从 1 开始" in prompt
    assert "bbox 必须使用 0 到 1 的归一化坐标" in prompt
    assert 'OCR=[{"image_index": 1' in prompt
    assert 'LAYOUT={"1":' in prompt
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
& 'C:\Users\97020\Desktop\daily-record-ocr-lite\.venv\Scripts\python.exe' `
  -m pytest tests_lite/test_pipeline_v2_prompt.py -q
```

Expected: `FAIL` because `build_vision_user_prompt` does not exist.

- [ ] **Step 3: Commit the RED test**

```powershell
git add tests_lite/test_pipeline_v2_prompt.py
git commit -m "test: require record schema in vision prompt"
```

### Task 2: Add the minimal prompt builder

**Files:**
- Modify: `lite_app/pipeline_v2.py:258-310`
- Test: `tests_lite/test_pipeline_v2_prompt.py`

- [ ] **Step 1: Add the pure builder**

Add above `analyze_job_v2`:

```python
def build_vision_user_prompt(
    schema_config: dict[str, Any],
    ocr_evidence: list[dict[str, Any]],
    layout_prompt: dict[str, Any],
) -> str:
    schema_text = json.dumps(
        schema_config["schema"],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        f"{schema_config.get('instructions', '')}\n\n"
        "以下 JSON Schema 是必须严格遵守的正式输出契约：\n"
        f"JSON_SCHEMA={schema_text}\n"
        "source_image_index 必须从 1 开始。\n"
        "bbox 必须使用 0 到 1 的归一化坐标；无法可靠定位时返回 null。\n"
        "以下 OCR 与本地布局仅为辅助证据，可能有误：\n"
        f"OCR={json.dumps(ocr_evidence, ensure_ascii=False)}\n"
        f"LAYOUT={json.dumps(layout_prompt, ensure_ascii=False)}\n"
        "只返回严格符合上述 JSON Schema 的 JSON 对象。"
    )
```

- [ ] **Step 2: Route production prompt construction through the builder**

Replace the inline `user_prompt = (...)` block with:

```python
user_prompt = build_vision_user_prompt(
    schema_config,
    ocr_evidence,
    layout_prompt,
)
```

- [ ] **Step 3: Run the target test and verify GREEN**

Run:

```powershell
& 'C:\Users\97020\Desktop\daily-record-ocr-lite\.venv\Scripts\python.exe' `
  -m pytest tests_lite/test_pipeline_v2_prompt.py -q
```

Expected: `1 passed`.

- [ ] **Step 4: Run provider regression tests**

Run:

```powershell
& 'C:\Users\97020\Desktop\daily-record-ocr-lite\.venv\Scripts\python.exe' `
  -m pytest tests_lite/test_dashscope_probe_request.py -q
```

Expected: `5 passed`; request still contains `json_object` and
`enable_thinking=false`, with effective timeout at least 300 seconds.

- [ ] **Step 5: Commit the implementation**

```powershell
git add lite_app/pipeline_v2.py
git commit -m "fix: send record schema in Qwen vision prompt"
```

### Task 3: Verify the repository and local installation

**Files:**
- Source: `lite_app/pipeline_v2.py`
- Local runtime: `C:\Users\97020\Desktop\daily-record-ocr-lite\lite_app\pipeline_v2.py`

- [ ] **Step 1: Run repository quality gates**

```powershell
ruff check .
git diff --check
& 'C:\Users\97020\Desktop\daily-record-ocr-lite\.venv\Scripts\python.exe' `
  -m pytest -m "not real_ocr" -q
```

Expected: Ruff and diff check pass; all non-real-OCR tests pass.

- [ ] **Step 2: Run Secret scans**

```powershell
git grep -n -E 'sk-(ws|sp)-[A-Za-z0-9._-]+'
git diff HEAD~2 | Select-String -Pattern 'sk-(ws|sp)-[A-Za-z0-9._-]+'
```

Expected: zero matches.

- [ ] **Step 3: Apply the verified production change to the local runtime**

Apply the same `pipeline_v2.py` diff to the desktop installation without changing
`data/settings.json`, `data/secrets.env`, old jobs or other runtime files.

- [ ] **Step 4: Run the target test against the desktop runtime**

```powershell
& 'C:\Users\97020\Desktop\daily-record-ocr-lite\.venv\Scripts\python.exe' `
  -m pytest tests_lite/test_pipeline_v2_prompt.py -q
```

Expected: `1 passed`.

### Task 4: Execute the same-image real Gate

**Files:**
- Read source image from Job `20260725-151256-8a9956`
- Create a new Job under `data/jobs/`
- Update: `docs/audits/QWEN_FIVE_MINUTE_TIMEOUT_AUDIT.md`

- [ ] **Step 1: Restart only the local service process**

Verify the PID listening on port 8765 belongs to this application, stop it, and start
the desktop instance hidden. Preserve all user configuration and job files.

- [ ] **Step 2: Re-run health checks**

Run real `test-vision` and OCR self-test if setup health requires it. Record only
sanitized host, Key type, model, latency, HTTP status and capability booleans.

- [ ] **Step 3: Create a new same-image Job**

Upload the exact source image from Job `20260725-151256-8a9956`. Verify SHA-256 equality
and obtain a new Job ID; never overwrite the prior `FAILED_SCHEMA` evidence.

- [ ] **Step 4: Poll to a terminal state**

Gate requires:

```text
model content received
vision/raw_response.txt exists
vision/structured_result.json exists
fatal Schema errors = 0
FinalResult exists
status = READY or REVIEW_REQUIRED
Excel export succeeds
```

If any condition fails, keep PR #4 Draft and report the exact failing stage.

- [ ] **Step 5: Update the audit report**

Record:

- RED/GREEN and full test counts;
- new Job ID and source hash;
- OCR/Vision timings and cache state when available;
- content character count without raw business content;
- Schema, FinalResult and Excel status;
- Secret scan and CI status;
- explicit merge/Tag/Release decision.

- [ ] **Step 6: Commit, push and request independent review**

```powershell
git add docs/audits/QWEN_FIVE_MINUTE_TIMEOUT_AUDIT.md
git commit -m "docs: record Qwen schema prompt validation"
git push origin fix/qwen-five-minute-timeout
```

Keep PR #4 Draft until both the real Gate and CI succeed.
