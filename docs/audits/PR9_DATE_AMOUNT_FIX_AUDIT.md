# PR #9 Date and Numeric Association Remediation Audit

Date: 2026-07-28
Branch: `feat/personal-knowledge-layer`
PR: #9 (must remain Draft)
Remediated code head: `851f2f779770856a6289405e694690d7fb2aac4d`

## Decision

The code remediation is verified locally, but the formal real-job release Gate is still blocked by a remote streamed-response disconnect during the full business prompt. This report does **not** authorize Ready for review, Merge, Tag, or Release.

## Scope

This remediation intentionally covers only:

1. field-level and formula-level safety for OCR numeric association;
2. conservative formula-local date recovery when the VLM date is empty;
3. one runtime resolver for the private knowledge database;
4. local setup-artifact exclusion.

It does not add retries, a longer timeout, OCR warmup, multi-core work, macOS work, or a Pipeline redesign.

## Root causes confirmed

### Numeric fields

The layout fallback previously selected the highest-scoring numeric pair even when no material/process field anchor was present. When a structured record had no `record_bbox`, a same-name field from another formula could also be selected. A coarse concatenated OCR token could therefore be reused across multiple amount fields, while a process value from an earlier formula could overwrite a later VLM value.

### Dates

Formula dates were used for evidence-region positioning but did not enter Fusion when the VLM left `record_date` empty. Some OCR lines contained malformed or concatenated date text. Guessing delimiters would create unsafe history ordering.

### Private knowledge database

Knowledge pages, recognition retrieval, confirmation write-back, correction logging, grouping review, and export had multiple path implementations. A private runtime could display one database while another subsystem wrote to the default database.

## Implemented safeguards

### Numeric association

- Layout numeric candidates now require a material/process anchor by token id, exact normalized anchor text, or anchor bbox overlap.
- The current formula region is preferred over a coarse layout record for pair containment.
- Formula regions are resolved once from structured formulas, OCR anchors, and layout evidence, then shared with Fusion and review evidence.
- An unanchored or cross-formula OCR numeric token is rejected instead of being split, repaired, or guessed.
- When OCR evidence is rejected, the independent VLM value remains and requires review according to the existing Fusion policy.

### Date recovery

- Recovery runs only when the VLM date is empty.
- Only one valid date inside the upper date band of the current formula region is accepted.
- The original handwritten form remains the displayed value.
- The existing date service derives an ISO sort value for knowledge history without rewriting the original value.
- Invalid calendar dates, incomplete text, multiple dates, neighboring-formula dates, and delimiter-loss strings are rejected.
- Every recovered date is `NEED_REVIEW`; knowledge history can never overwrite it.

### Private knowledge database

- `resolve_knowledge_db_path()` is the sole runtime resolver.
- `KNOWLEDGE_DB_PATH` overrides the active data-root default.
- Pipeline retrieval, knowledge pages, confirmation, correction logging, grouping review, and export use the same resolver.
- Private SQLite data remains local and ignored by Git.

## Automated verification

Final non-real suite:

```text
524 passed, 5 deselected
```

Focused evidence:

- 82 association/Fusion/date-safety tests passed after independent-review remediation.
- 59 date, date-sort, Pipeline, and knowledge-history tests passed.
- 43 Pipeline/FinalResult/review/export integration tests passed.
- 18 knowledge path/page/write-back/export/API tests passed.

Quality Gates:

```text
Ruff: All checks passed
git diff --check: passed
tracked Secret scan: 0 matches
branch diff Secret scan: 0 matches
new private path or Job-id scan: 0 matches
```

## Real-evidence local replay

The previous real OCR, layout, and structured VLM artifacts were replayed read-only through the new Fusion code. No old Job or user edit was changed.

Sanitized result:

- the later process value remained the VLM value and the earlier formula's OCR value was absent from its candidates;
- 13 second-page amount fields were evaluated;
- the concatenated long OCR token appeared 0 times as a final amount and 0 times as an amount candidate;
- both existing second-page VLM dates were preserved;
- none of the five first-page malformed OCR date lines was guessed; all remained for manual completion.

## Controlled Qwen A/B/C evidence

All calls used the official metered Alibaba-compatible host, `qwen3.7-plus`, `json_object`, `enable_thinking=false`, and an effective 300-second timeout. No key or raw business response is stored in this report.

| Case | Images | Request size | Result | Latency / content |
|---|---:|---:|---|---|
| A: probe image + minimal JSON marker prompt | 1 small probe | not retained | HTTP 200, status OK, all three capability flags true | 4,234 ms |
| B1: one real image + minimal JSON prompt | 1 | 85,751 bytes | success, JSON object | 8,811 ms; 476 chars |
| B2: both real images + minimal JSON prompt | 2 | 170,336 bytes | success, JSON object | 21,468 ms; 2,001 chars |
| C: both real images + full OCR/Layout/Knowledge/Schema prompt | 2 | 181,254 bytes | response headers received; no complete content; incomplete chunked read | failed before structured output |

Inference: the same two images succeed with the minimal prompt, while the full business request is only modestly larger. The remaining failure is associated with the full structured-generation/streaming stage rather than the endpoint, API key type, image count, or the 300-second timeout.

## Formal new-Job Gate

The new Job was created without modifying previous evidence.

Passed before remote failure:

- preprocessing completed;
- PP-OCRv6 completed in 2,424 ms;
- two-page OCR and layout artifacts were generated.

Blocked:

- complete model content;
- `vision/structured_result.json`;
- Schema validation;
- Fusion and FinalResult;
- `REVIEW_REQUIRED`/`READY` completion;
- formal Excel export.

The failed new Job is retained locally as evidence and is ignored by Git.

## Private-data boundary

The following remain local and untracked:

- private SQLite database and backups;
- settings and secrets;
- setup health and OCR setup overlay;
- source images and Jobs;
- OCR overlays and evidence crops;
- raw model responses, caches, and logs.

No local file was deleted to satisfy this Gate.

## Remaining blockers

1. Full business prompt must return complete model content on a fresh real Job.
2. That Job must produce structured result, valid Schema, Fusion, FinalResult, and review evidence.
3. User confirmation, knowledge write-back, READY, and formal Excel remain separate PR #9 product Gates.
4. Knowledge OFF/ON accuracy and the larger personal dataset Gate remain incomplete.

## Release recommendation

```text
PR #9 Ready: NO
Merge: NO
Tag: NO
Release: NO
```

The current commits may be pushed for Draft review only after an independent GPT review finds no P0/P1 code or privacy regression.

## Independent GPT review remediation

The first independent review correctly blocked the push and reproduced four gaps:

1. direct numeric evidence ids could bypass formula containment;
2. numeric bbox association could bypass formula containment;
3. a coarse VLM record bbox could override the safer local formula region;
4. one OCR numeric token could be claimed by multiple fields, while a coarse date token could cross a formula boundary.

The remediation now:

- requires every direct-id, bbox, center-distance, and layout numeric candidate to be fully contained by the current formula region;
- prefers the local formula region over the VLM record bbox for association;
- performs a Fusion-batch ownership pass and removes a reused OCR numeric token from every affected field;
- preserves each field's VLM value, forces `NEED_REVIEW`, and records `OCR_NUMERIC_TOKEN_REUSED`;
- requires the complete date token bbox to remain within the current formula's date band;
- adds explicit regression tests for all four cases;
- removes all trailing whitespace reported by range `git diff --check`.

A second independent review is required before Draft push. The formal real-job Gate remains blocked regardless of the code-review outcome.
