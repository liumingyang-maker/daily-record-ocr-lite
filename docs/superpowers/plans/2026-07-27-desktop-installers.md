# Desktop installers implementation plan

Branch: `feat/desktop-installers`  
Stacked base: `feat/evidence-first-product-workflow`  
Delivery: independent Draft PR; no merge, tag, release, signing or notarization.

## Task 1: platform paths and frozen resources

- Add failing tests for explicit data-directory overrides, Windows/macOS defaults and source checkout compatibility.
- Implement one resolver for replaceable app resources and persistent user data.
- Route settings, jobs and knowledge databases through the persistent data root.
- Verify existing source-mode tests remain green.

## Task 2: safe legacy-data import

- Add failing tests for source validation, non-destructive copying, explicit conflict confirmation, backup creation and secret-safe reports.
- Implement a migration service that never modifies the source and never silently overwrites a non-empty target.
- Add a first-run API/UI entry without exposing file contents in logs.

## Task 3: desktop launcher

- Add failing tests for loopback-only binding, dynamic port selection, instance state and second-launch behavior.
- Implement a cross-platform single-instance lock, local state file, background Uvicorn lifecycle, browser opening and optional tray menu.
- Provide a deterministic `--self-test` mode for native build gates.

## Task 4: stable update awareness

- Add failing tests for stable-tag selection, installed/source mode detection and failure-safe update results.
- Add a settings card and API that opens the latest stable GitHub Release without running Git against desktop installs.

## Task 5: reproducible packaging definitions

- Add pinned desktop build requirements.
- Add a PyInstaller onedir spec collecting app modules, config, templates, schemas and OCR runtime hooks.
- Add Inno Setup and macOS app/DMG scripts that preserve platform data directories.
- Add artifact naming, checksums and provenance generation.

## Task 6: native CI and release gates

- Add Windows x64 and macOS arm64 native build jobs.
- Install, launch, test loopback health, test single-instance behavior and run a real PP-OCRv6 inference.
- Upload clearly labelled unsigned test artifacts for Draft PRs.
- Add signing/notarization gates that block formal assets when required secrets are missing.

## Task 7: verification, audit and Draft PR

- Run unit/integration tests, Ruff, diff check, real OCR and secret scans.
- Run available Windows native packaging checks locally; rely on native macOS CI for DMG verification.
- Generate a copyable independent-GPT audit document with unresolved release blockers.
- Push and open a stacked Draft PR targeting `feat/evidence-first-product-workflow`.
