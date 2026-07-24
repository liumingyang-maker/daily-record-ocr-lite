# Qwen3.7 Plus Five-Minute Timeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Alibaba-hosted `qwen3.7-plus` up to at least five minutes for a formal vision request and prove whether the same real handwritten-record task can produce a valid final result.

**Architecture:** Keep the change inside `OpenAICompatibleVisionProvider`, next to the existing Qwen request-parameter specialization. Raise only a too-small Qwen timeout with `max(current, 300)`; do not change other providers or user values above five minutes. Validate the complete real pipeline separately from the marker probe.

**Tech Stack:** Python 3.11, httpx, pytest, FastAPI pipeline, GitHub Actions.

---

### Task 1: Lock the Qwen timeout contract

**Files:**
- Modify: `tests_lite/test_dashscope_probe_request.py`

- [ ] **Step 1: Write the failing tests**

Add tests which instantiate the real Provider and assert:

```python
def test_qwen37_plus_uses_at_least_five_minute_timeout():
    provider = OpenAICompatibleVisionProvider({
        "base_url": "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        "endpoint": "/chat/completions",
        "api_key": "test-key",
        "model": "qwen3.7-plus",
        "timeout_seconds": 120,
    })
    assert provider.timeout == 300


def test_qwen37_plus_preserves_longer_timeout():
    provider = OpenAICompatibleVisionProvider({
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen3.7-plus",
        "timeout_seconds": 420,
    })
    assert provider.timeout == 420


def test_other_models_keep_configured_timeout():
    provider = OpenAICompatibleVisionProvider({
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "timeout_seconds": 120,
    })
    assert provider.timeout == 120
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m pytest tests_lite/test_dashscope_probe_request.py -q
```

Expected: the 120-to-300 assertion fails because current code retains 120.

### Task 2: Implement the minimum timeout

**Files:**
- Modify: `lite_app/vision/openai_compatible.py`
- Test: `tests_lite/test_dashscope_probe_request.py`

- [ ] **Step 1: Add a single Qwen predicate and timeout policy**

Compute whether the request is Alibaba-hosted Qwen3.7 Plus once during initialization:

```python
self.is_alibaba_qwen37 = (
    (urlparse(self.base_url).hostname or "").lower().endswith(".aliyuncs.com")
    and self.model.lower() == "qwen3.7-plus"
)
if self.is_alibaba_qwen37:
    self.timeout = max(self.timeout, 300)
```

Reuse the same predicate when adding `json_object` and `enable_thinking=false`.

- [ ] **Step 2: Run focused tests and verify GREEN**

Run:

```powershell
python -m pytest tests_lite/test_dashscope_probe_request.py -q
```

Expected: all focused tests pass.

- [ ] **Step 3: Commit the TDD change**

```powershell
git add lite_app/vision/openai_compatible.py tests_lite/test_dashscope_probe_request.py
git commit -m "fix: allow five minutes for Qwen vision requests"
```

### Task 3: Run repository gates

**Files:**
- No production-file changes expected.

- [ ] **Step 1: Run static and unit gates**

```powershell
ruff check .
git diff --check
python -m pytest -m "not real_ocr" -q
```

Expected: Ruff and diff checks pass; all non-real tests pass.

- [ ] **Step 2: Run Secret and local-artifact checks**

Confirm tracked content and the branch diff have no `sk-ws` or `sk-sp` key, and no local settings, task data, logs, raw responses, or source images are added.

### Task 4: Run the real full-task validation

**Files:**
- Runtime-only data under the ignored installation `data/jobs/`.
- Do not commit runtime files.

- [ ] **Step 1: Apply the reviewed Provider change to the installed v1.0.1 instance**

Copy only the reviewed `lite_app/vision/openai_compatible.py` implementation to the installed instance after preserving its original file for rollback outside Git tracking.

- [ ] **Step 2: Create a new job from the original failed task image**

Use:

```text
C:\Users\97020\Desktop\daily-record-ocr-lite\data\jobs\
20260724-201326-b247dd\source\source_01_433189ab1f8334b21f79da261b97648a.jpg
```

Do not overwrite job `20260724-201326-b247dd`.

- [ ] **Step 3: Wait up to five minutes and classify the result**

Require one of these evidence-backed outcomes:

- completed structured result plus FinalResult/export readiness;
- response received but JSON/Schema/semantic failure;
- 300-second timeout;
- HTTP/authentication failure.

Do not treat HTTP 200 or the marker probe alone as success.

### Task 5: Review and PR

**Files:**
- Create: `docs/audits/QWEN_FIVE_MINUTE_TIMEOUT_AUDIT.md`

- [ ] **Step 1: Write a copyable audit report**

Include branch SHA, test counts, real-task job ID, elapsed time, final status, structural validation result, Secret scan, known limitations, and no raw response or key.

- [ ] **Step 2: Run independent GPT standards and specification review**

Fix blocker, severe, or important findings and rerun affected tests.

- [ ] **Step 3: Push and create a PR to master**

Wait for all PR CI before any merge decision.
