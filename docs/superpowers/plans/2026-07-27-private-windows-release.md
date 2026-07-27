# Private Windows Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, validate and privately publish a Windows 10/11 x64 personal installer containing the runtime, OCR model, personal seed database, evidence and default Qwen configuration while preserving learned data across upgrades.

**Architecture:** Keep generic packaging in the public repository and private overlay inputs outside Git. Build a versioned seed bundle, inject the private key only during the private build, initialize mutable data on first install, and never overwrite the active database during upgrades.

**Tech Stack:** Python 3.11, PyInstaller, Inno Setup, PowerShell, SQLite, GitHub private repository and Releases.

---

## File map

- `packaging/personal/personal-bundle.schema.json`: private overlay manifest.
- `packaging/personal/build_personal.ps1`: local/private build entry.
- `lite_app/personal_seed.py`: first-install seed and upgrade preservation.
- `scripts/verify_personal_bundle.py`: fail-closed input verification.
- `scripts/verify_personal_install.py`: installed app/DB/OCR/vision checks.
- `packaging/windows/setup-personal.iss`: personal installer overlay.
- `docs/PERSONAL_WINDOWS_INSTALL.md`: install/update/recovery.
- `docs/audits/PERSONAL_V1.1.0_AUDIT.md`: copyable GPT audit.
- `tests_lite/test_personal_seed.py`
- `tests_lite/test_personal_packaging.py`
- `tests_lite/test_personal_installer_contract.py`

### Task 1: Personal seed preservation

- [ ] Write failing tests for first install, upgrade, corrupt database recovery and
explicit reset. First install copies the seed; upgrade preserves active formulas,
lexicon feedback and user key override.

- [ ] Witness red.

- [ ] Implement `initialize_personal_seed(seed_dir, data_dir, version)`. Validate
manifest/checksums, copy through a temporary path and atomic replace only when no
active database exists. Back up before every migration.

- [ ] Run green.

### Task 2: Fail-closed private bundle verifier

- [ ] Write failing tests for missing DB, missing evidence, checksum mismatch, source
Excel present, raw response/log present, secret present in a report, wrong core SHA
and wrong schema version.

- [ ] Witness red.

- [ ] Implement verifier returning a redacted manifest summary. It may verify that a
runtime secret exists during build, but must never print or persist the value.

- [ ] Run green.

### Task 3: Personal build entry

- [ ] Write failing command-contract tests for required `-CoreRoot`, `-PrivateInput`,
`-OutputDir` and version arguments. Assert output remains inside the designated build
directory.

- [ ] Witness red.

- [ ] Implement `build_personal.ps1` to:

1. verify clean/pinned core;
2. verify private input;
3. stage seed database and evidence;
4. bundle Python, PaddleOCR and verified model packages;
5. inject the runtime vision key from process/private secret storage;
6. build PyInstaller payload;
7. build the Inno Setup installer;
8. write manifest and SHA-256;
9. run installed-layout verification.

- [ ] Run contract tests green.

### Task 4: Installer behavior

- [ ] Write failing installer contract tests asserting Windows 10/11 x64, desktop
shortcut, start-menu shortcut, user-data preservation, opt-in purge, doctor launch
and unsigned-build labeling.

- [ ] Witness red.

- [ ] Add `setup-personal.iss` reusing generic installer functions. Install immutable
program files separately from mutable user data. Uninstall keeps data unless the user
explicitly selects purge.

- [ ] Run green and compile the installer.

### Task 5: Installed acceptance

- [ ] Write failing verifier tests for version, seed data counts, evidence existence,
OCR runtime, model paths, Qwen endpoint/model/timeout/json_object/thinking settings,
settings override and Excel export.

- [ ] Witness red.

- [ ] Implement the verifier with redacted output and distinct exit codes for install,
data, OCR, vision, recognition and export failures.

- [ ] Run green.

### Task 6: Private GitHub repository

- [ ] Create private repository `liumingyang-maker/daily-record-ocr-private`.
- [ ] Confirm visibility is `PRIVATE` before pushing any content.
- [ ] Commit only private build configuration, redacted manifests, permitted database/
evidence assets and documentation. Never commit raw source workbooks or a plaintext
key.
- [ ] Add a README explaining pinned core updates, private rebuild, backup, install,
restore and latest stable Release usage.

### Task 7: Real Windows and model gates

- [ ] Build `v1.1.0-personal.1`.
- [ ] Install using the produced installer.
- [ ] Run full doctor.
- [ ] Run real PP-OCRv6 tests with at least one actual inference pass.
- [ ] Run Qwen3.7 Plus probe: HTTP 200, marker correct, JSON parsed.
- [ ] Run at least one complete multi-card image task through structured result,
Schema, FinalResult, confirmed knowledge and downloadable Excel.
- [ ] Run the real knowledge A/B benchmark and record only redacted aggregates.

### Task 8: Audit, review and private Release

- [ ] Write `docs/audits/PERSONAL_V1.1.0_AUDIT.md` with a copyable GPT review prompt,
scope, exclusions, SHAs, PRs, CI, data totals, extraction sampling, OCR/Qwen results,
knowledge A/B, secret scans, installer verification, assets and residual risks.

- [ ] Run independent GPT standards and spec review. Resolve or explicitly accept
every finding; unresolved serious findings block release.

- [ ] Run:

```powershell
python -m pytest -m "not real_ocr" -q
python -m ruff check .
git diff --check
git grep -n -E 'sk-(ws|sp)-[A-Za-z0-9._-]+'
git diff | Select-String -Pattern 'sk-(ws|sp)-[A-Za-z0-9._-]+'
```

- [ ] Push the public core feature branch and create/update its Draft PR.
- [ ] Wait for all CI checks; do not merge on failure.
- [ ] Push the private repository only after visibility and secret scans pass.
- [ ] Create private tag and Release `v1.1.0-personal.1`.
- [ ] Attach installer, checksums, manifest, installation guide and redacted audit.
- [ ] Verify Release assets can be downloaded and their SHA-256 values match.
