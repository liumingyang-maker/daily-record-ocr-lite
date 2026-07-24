# Latest Stable Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make README and the AI upgrade protocol guide users to the newest stable Release Tag, with a Windows updater that safely resolves and checks out that Tag.

**Architecture:** Keep one existing Windows update entry point and add a small `latest` resolution branch before checkout. README provides the short user/AI entry point; `docs/AI_AGENT_UPGRADE.md` remains the authoritative cross-platform procedure. Contract tests inspect the PowerShell and documentation because CI cannot safely mutate its own checkout to exercise a real upgrade.

**Tech Stack:** PowerShell, Git, Markdown, Python 3.11/3.12, pytest, GitHub Actions.

---

### Task 1: Add failing stable-update contracts

**Files:**
- Modify: `tests_lite/test_v1_contracts.py`
- Test: `tests_lite/test_v1_contracts.py`

- [ ] **Step 1: Add updater contract tests**

Extend the existing Windows updater test with assertions equivalent to:

```python
def test_windows_updater_targets_latest_stable_tag_safely():
    from lite_app.config import PROJECT_ROOT

    script = (PROJECT_ROOT / "install" / "update-windows.ps1").read_text(
        encoding="utf-8-sig"
    )
    assert '[string]$Ref = "latest"' in script
    assert "--sort=-v:refname" in script
    assert r"'^v\d+\.\d+\.\d+$'" in script
    assert "git checkout --detach $TargetRef" in script
    assert "git pull --ff-only origin $TargetRef" in script
    assert '\"refs/tags/$TargetRef\"' in script
    assert "git reset" not in script
    assert "git clean" not in script
    assert "Remove-Item" not in script
```

- [ ] **Step 2: Add documentation contract tests**

Add:

```python
def test_readme_and_ai_upgrade_guide_target_latest_stable_release():
    from lite_app.config import PROJECT_ROOT

    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    guide = (PROJECT_ROOT / "docs" / "AI_AGENT_UPGRADE.md").read_text(
        encoding="utf-8"
    )
    for required in (
        "最新稳定 Release Tag",
        "AGENTS.md",
        "docs/AI_AGENT_UPGRADE.md",
        "UPGRADE_REPORT",
    ):
        assert required in readme
    for required in (
        "^v[0-9]+\\.[0-9]+\\.[0-9]+$",
        "git fetch --tags origin",
        "git checkout --detach",
        'python -m pytest -m "not real_ocr" -q',
        "python -m pytest -m real_ocr -q -s",
        "python scripts/doctor.py --full --json",
        "UPGRADE_REPORT",
    ):
        assert required in guide
```

- [ ] **Step 3: Run the tests and verify RED**

Run:

```text
python -m pytest tests_lite/test_v1_contracts.py -k "windows_updater or ai_upgrade" -q
```

Expected: failures for the old `master` default and missing latest-stable documentation.

- [ ] **Step 4: Commit the failing contracts**

```text
git add tests_lite/test_v1_contracts.py
git commit -m "test: define latest stable update contracts"
```

### Task 2: Make the Windows updater Release-Tag aware

**Files:**
- Modify: `install/update-windows.ps1`
- Test: `tests_lite/test_v1_contracts.py`

- [ ] **Step 1: Change the default and capture the previous revision**

Use the following parameter default, then capture the revision only after the script has set
`$Root` and called `Set-Location $Root`:

```powershell
param(
    [string]$Ref = "latest",
    [ValidateSet("Cpu", "Gpu")]
    [string]$OcrMode = "Cpu",
    [string]$PaddleInstallCommand = "",
    [switch]$SkipOcr
)

$PreviousCommit = (git rev-parse HEAD).Trim()
$PreviousLabel = (git describe --tags --exact-match 2>$null)
if (-not $PreviousLabel) {
    $PreviousLabel = $PreviousCommit
}
```

- [ ] **Step 2: Resolve only stable semantic-version Tags**

After the existing worktree check and backup, replace direct checkout/pull with:

```powershell
git fetch --tags origin
if ($LASTEXITCODE -ne 0) {
    throw "无法从 origin 获取版本标签。"
}

$TargetRef = $Ref
if ($Ref -eq "latest") {
    $TargetRef = git tag --list "v[0-9]*" --sort=-v:refname |
        Where-Object { $_ -match '^v\d+\.\d+\.\d+$' } |
        Select-Object -First 1
    if (-not $TargetRef) {
        throw "没有找到稳定 Release Tag（格式 v主版本.次版本.修订版本）。"
    }
}

$TargetCommit = (git rev-list -n 1 $TargetRef).Trim()
if (-not $TargetCommit) {
    throw "无法解析更新目标: $TargetRef"
}
if ($PreviousCommit -eq $TargetCommit) {
    Write-Host "已经是目标稳定版本 $TargetRef；无需重复安装。"
    Write-Host "数据备份位于 $Backup"
    exit 0
}
```

- [ ] **Step 3: Separate Tag checkout from branch fast-forward**

Use:

```powershell
git show-ref --verify --quiet "refs/tags/$TargetRef"
$IsTag = $LASTEXITCODE -eq 0
if ($IsTag) {
    git checkout --detach $TargetRef
} else {
    git checkout $TargetRef
    if ($LASTEXITCODE -ne 0) {
        throw "无法切换到更新目标: $TargetRef"
    }
    git pull --ff-only origin $TargetRef
}
if ($LASTEXITCODE -ne 0) {
    throw "无法更新到目标: $TargetRef"
}
```

- [ ] **Step 4: Report old version, new version, and rollback point**

End with:

```powershell
Write-Host "更新完成：$PreviousLabel -> $TargetRef"
Write-Host "回滚点：$PreviousCommit"
Write-Host "数据备份位于 $Backup"
```

- [ ] **Step 5: Run updater contract tests**

Run:

```text
python -m pytest tests_lite/test_v1_contracts.py -k "windows_updater" -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit the updater**

```text
git add install/update-windows.ps1
git commit -m "fix: update Windows installs to latest stable tag"
```

### Task 3: Add the README quick-update entry

**Files:**
- Modify: `README.md`
- Test: `tests_lite/test_v1_contracts.py`

- [ ] **Step 1: Add a section after the stable-version introduction**

The section must include this Windows command:

```powershell
.\install\update-windows.ps1
```

It must also include a directly copyable AI prompt with these requirements:

```text
请读取 AGENTS.md 和 docs/AI_AGENT_UPGRADE.md，把当前安装安全更新到最新稳定 Release Tag。
更新前备份 data/，不得执行 git reset、git clean 或删除用户配置，不得回显 API Key。
更新后运行非 real_ocr 测试、至少一次真实 OCR 推理和 doctor --full，并输出 UPGRADE_REPORT。
如果已是最新版，不要重复安装，只执行健康检查并报告。
```

- [ ] **Step 2: Link the authoritative guide**

Link `docs/AI_AGENT_UPGRADE.md` immediately below the prompt and state that `master` is opt-in, not the default for ordinary users.

- [ ] **Step 3: Run the documentation contract**

Run:

```text
python -m pytest tests_lite/test_v1_contracts.py -k "ai_upgrade" -q
```

Expected: the README portion passes once the guide task is also complete; a remaining guide failure is acceptable until Task 4.

### Task 4: Rewrite the AI upgrade protocol

**Files:**
- Modify: `docs/AI_AGENT_UPGRADE.md`
- Test: `tests_lite/test_v1_contracts.py`

- [ ] **Step 1: Define preflight and stable Tag resolution**

Document:

```text
git status --porcelain
git rev-parse HEAD
git describe --tags --exact-match
git fetch --tags origin
```

Require stable Tags to match `^v[0-9]+\.[0-9]+\.[0-9]+$`, use Git version sorting, and stop if no stable Tag exists.

- [ ] **Step 2: Document Windows, Linux, and macOS paths**

Windows:

```powershell
.\install\update-windows.ps1
```

Linux/macOS AI procedure:

```text
1. Copy data/ to backups/data-<timestamp>/.
2. Run git fetch --tags origin.
3. Resolve the highest stable semantic-version Tag.
4. Run git checkout --detach <latest-stable-tag>.
5. Run ./install/install-linux.sh or ./install/install-macos.sh with the officially verified Paddle command where required.
```

State that ignored user configuration remains in `data/`, and forbid `reset`, `clean`, automatic data deletion, or automatic rollback.

- [ ] **Step 3: Define verification and UPGRADE_REPORT**

Require:

```text
python -m pytest -m "not real_ocr" -q
python -m pytest -m real_ocr -q -s
python scripts/doctor.py --full --json
```

The report fields are: operating system, old commit/tag, target stable Tag, new commit, backup path, dependency actions, non-real test count, real OCR pass count, doctor state, application URL, failure details, and rollback commit. Secret values are prohibited.

- [ ] **Step 4: Run the combined contracts**

Run:

```text
python -m pytest tests_lite/test_v1_contracts.py -k "windows_updater or ai_upgrade" -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit README and protocol**

```text
git add README.md docs/AI_AGENT_UPGRADE.md tests_lite/test_v1_contracts.py
git commit -m "docs: add fast stable update instructions"
```

### Task 5: Verify, audit, and publish the documentation update

**Files:**
- Create: `docs/audits/FAST_STABLE_UPDATE_AUDIT.md`
- Modify only if review finds an issue: files from Tasks 1–4

- [ ] **Step 1: Run full local Gates**

```text
ruff check .
git diff --check
python -m pytest -m "not real_ocr" -q
git grep -n -E 'sk-(ws|sp)-[A-Za-z0-9._-]+'
```

Expected: Ruff/diff/tests pass and Secret scan has no matches.

- [ ] **Step 2: Create the copyable audit report**

Report fixed point `master` before this branch, commits, changed files, stable Tag behavior, data protection, selected tests, full Gates, Secret scan, prohibited scope, and a self-contained GPT review prompt. Do not include local configuration or raw API responses.

- [ ] **Step 3: Run independent GPT review**

One reviewer checks `AGENTS.md` and repository standards; another checks this plan/spec. Record every finding as fixed, accepted, or blocking in the audit report.

- [ ] **Step 4: Re-run Gates after review changes**

Run:

```text
ruff check .
git diff --check
python -m pytest -m "not real_ocr" -q
```

Expected: all pass.

- [ ] **Step 5: Commit and push**

```text
git add docs/audits/FAST_STABLE_UPDATE_AUDIT.md
git commit -m "docs: audit latest stable update flow"
git push -u origin docs/fast-stable-update
```

- [ ] **Step 6: Create PR and wait for CI**

Create a PR to `master` titled `docs: add latest stable AI update flow`. The PR body must list the stable Tag policy, Windows script correction, data safety, tests, and audit link. Merge only after all required checks pass, then verify the README on GitHub master.
