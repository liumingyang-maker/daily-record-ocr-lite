# Sticky Cropped Evidence and Date Sorting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为每条配方生成可安全回退的裁剪证据并在审查卡片内粘性展示，同时保留日期原文、生成机器排序日期并安全迁移个人知识库。

**Architecture:** OCR 与 Qwen 继续处理整图；新增纯本地 `FormulaEvidenceResolver`，融合可选模型坐标、OCR/layout 锚点和安全回退区域，从原始上传图生成审查裁剪及带 SHA-256 的 manifest。FinalResult 继续保存日期原文；独立日期解析器只生成知识历史使用的 ISO 排序值和状态。审查 API 仅暴露由 Job/formula 身份映射得到的受控文件 URL。

**Tech Stack:** Python 3.11、FastAPI、Pillow/OpenCV、SQLite、原生 JavaScript/CSS、pytest、Ruff

---

## Task 1: 日期原文解析与审查编辑

**Files:**
- Create: `lite_app/date_values.py`
- Modify: `lite_app/review_editor.py`
- Modify: `lite_app/review_view.py`
- Modify: `lite_app/static/review.js`
- Test: `tests_lite/test_date_values.py`
- Test: `tests_lite/test_review_editor.py`
- Test: `tests_lite/test_review_view.py`

- [ ] **Step 1: 写日期解析失败测试**

  覆盖 `24.7.19 -> 2024-07-19`、`22/9/27 -> 2022-09-27`、四位年份、`.` `/` `-`、空值、非法日历日期与不可解析原文。断言解析器返回 `(raw, sort_value, status)`，原文永不改写。

- [ ] **Step 2: 运行日期测试并确认 RED**

  Run: `.venv\Scripts\python.exe -m pytest tests_lite/test_date_values.py -q`

- [ ] **Step 3: 最小实现日期解析器**

  使用完整匹配和 `datetime.date` 严格校验；两位年份固定映射至 `20xx`；空值为 `UNKNOWN`，合法值为 `KNOWN`，非空非法值为 `UNPARSED`。

- [ ] **Step 4: 写审查编辑失败测试**

  断言审查编辑接受并原样保存 `24.7.19`、`22/9/27`，拒绝 `2026-02-30`，且 review view 返回原始文本与内部日期状态。

- [ ] **Step 5: 实现文本日期控件与服务器校验**

  将浏览器日期输入从 `type=date` 改为普通文本；后端调用统一解析器，仅拒绝 `UNPARSED`，不把合法原文改成 ISO；显示“保留原写法，系统用于排序”的辅助说明。

- [ ] **Step 6: 验证 Task 1**

  Run: `.venv\Scripts\python.exe -m pytest tests_lite/test_date_values.py tests_lite/test_review_editor.py tests_lite/test_review_view.py -q`

- [ ] **Step 7: 提交 Task 1**

  `git add lite_app/date_values.py lite_app/review_editor.py lite_app/review_view.py lite_app/static/review.js tests_lite/test_date_values.py tests_lite/test_review_editor.py tests_lite/test_review_view.py && git commit -m "feat: preserve handwritten formula dates"`

## Task 2: 知识库原始日期、排序日期与来源顺序

**Files:**
- Modify: `lite_app/knowledge/migrations.py`
- Modify: `lite_app/knowledge/history.py`
- Modify: `lite_app/knowledge/exporter.py`
- Modify: `lite_app/knowledge/package.py`
- Test: `tests_lite/test_knowledge_migrations.py`
- Test: `tests_lite/test_knowledge_history.py`
- Test: `tests_lite/test_knowledge_package.py`

- [ ] **Step 1: 写 v4 迁移失败测试**

  断言迁移前自动备份；新增 `record_date_raw`；旧合法日期同时保留原文并规范化 `record_date` 排序列；旧非法值原文保留、排序列置空、状态为 `UNPARSED`；事务失败可回滚。

- [ ] **Step 2: 写历史排序失败测试**

  覆盖已知日期按 ISO 排序；同一来源内夹在两个日期之间的未知日期按 `source_order` 保持中间位置；无日期锚点时以录入时间和来源顺序稳定排序；详情与知识页面显示原文。

- [ ] **Step 3: 运行知识测试并确认 RED**

  Run: `.venv\Scripts\python.exe -m pytest tests_lite/test_knowledge_migrations.py tests_lite/test_knowledge_history.py tests_lite/test_knowledge_package.py -q`

- [ ] **Step 4: 实现 v4 非破坏迁移**

  保留现有 `formulas.record_date` 为 ISO 排序列，新增 `record_date_raw`；迁移逐行调用统一日期解析器；迁移前沿用 SQLite 在线备份；扩展 `date_status` 允许应用层 `UNPARSED`。

- [ ] **Step 5: 实现写入、查询与导出**

  用户确认写回时保存原文、排序值、状态和 `source_order`；API 使用 `record_date_raw` 展示；SQL/应用层使用排序值与稳定 rank 排序，但不为未知日期制造日期。

- [ ] **Step 6: 验证 Task 2**

  Run: `.venv\Scripts\python.exe -m pytest tests_lite/test_knowledge_migrations.py tests_lite/test_knowledge_history.py tests_lite/test_knowledge_package.py tests_lite/test_knowledge_pages.py -q`

- [ ] **Step 7: 提交 Task 2**

  `git add lite_app/knowledge tests_lite/test_knowledge_migrations.py tests_lite/test_knowledge_history.py tests_lite/test_knowledge_package.py tests_lite/test_knowledge_pages.py && git commit -m "feat: sort history without rewriting source dates"`

## Task 3: 配方级证据定位与安全裁剪产物

**Files:**
- Create: `lite_app/evidence_regions.py`
- Modify: `lite_app/pipeline_v2.py`
- Modify: `lite_app/contracts.py`
- Test: `tests_lite/test_evidence_regions.py`
- Test: `tests_lite/test_pipeline_knowledge.py`
- Test: `tests_lite/test_v1_contracts.py`

- [ ] **Step 1: 写 bbox 验证与融合失败测试**

  覆盖正常、越界、反向、过小、过大、乱序、异常重叠；模型/本地一致时安全并集；冲突时较大安全区；双方不可用时页面内容区或整图；四周 padding 与 clamp。

- [ ] **Step 2: 写裁剪产物安全失败测试**

  断言安全 formula 文件名、原图及裁剪 SHA-256、像素/归一化坐标、定位来源写入 `review/evidence_regions.json`；路径穿越、错误公式 ID、原图 hash 改变均不能返回裁剪。

- [ ] **Step 3: 运行证据测试并确认 RED**

  Run: `.venv\Scripts\python.exe -m pytest tests_lite/test_evidence_regions.py -q`

- [ ] **Step 4: 实现纯本地 resolver 与 artifact store**

  使用模型 `record_bbox` 候选；从 OCR token 的配方序号、日期形态、材料/数量行和相邻锚点构造本地候选；失败时静默扩大到安全区域或整图。从原始上传图生成高质量 JPEG，不把裁剪失败升级为 Job 失败。

- [ ] **Step 5: 扩展 Qwen 紧凑合同**

  在每条 record 中加入可选归一化 `record_bbox`，明确坐标仅用于定位；Prompt 保持整图输入与现有业务字段，不增加逐配方模型调用。

- [ ] **Step 6: 接入 Pipeline**

  structured result/FinalResult 成功后生成证据；使用持久化 OCR/layout 与原图；异常只写脱敏状态，不记录完整响应或本机私密路径。

- [ ] **Step 7: 验证 Task 3**

  Run: `.venv\Scripts\python.exe -m pytest tests_lite/test_evidence_regions.py tests_lite/test_pipeline_knowledge.py tests_lite/test_v1_contracts.py -q`

- [ ] **Step 8: 提交 Task 3**

  `git add lite_app/evidence_regions.py lite_app/pipeline_v2.py lite_app/contracts.py tests_lite/test_evidence_regions.py tests_lite/test_pipeline_knowledge.py tests_lite/test_v1_contracts.py && git commit -m "feat: generate formula evidence crops"`

## Task 4: 受控证据 API 与审查视图

**Files:**
- Modify: `lite_app/main.py`
- Modify: `lite_app/review_view.py`
- Test: `tests_lite/test_review_api.py`
- Test: `tests_lite/test_review_view.py`

- [ ] **Step 1: 写 API 失败测试**

  断言 review view 为每条配方返回 `crop_url` 与 `full_image_url`；缺失/损坏裁剪自动回退整图；错误 Job、错误 formula ID、路径穿越和 hash 不匹配被拒绝。

- [ ] **Step 2: 运行测试并确认 RED**

  Run: `.venv\Scripts\python.exe -m pytest tests_lite/test_review_api.py tests_lite/test_review_view.py -q`

- [ ] **Step 3: 实现身份映射式证据路由**

  路由只接受 Job ID 与已存在 formula ID，从 manifest 解析真实文件；解析后验证仍位于 Job 目录并核对 SHA-256；不得接受任意相对路径。

- [ ] **Step 4: 实现视图回退**

  crop 可验证时使用裁剪；否则 `image_url` 使用整图；始终保留 `full_image_url`；不向浏览器暴露磁盘绝对路径或 hash 内部细节。

- [ ] **Step 5: 验证并提交 Task 4**

  Run: `.venv\Scripts\python.exe -m pytest tests_lite/test_review_api.py tests_lite/test_review_view.py -q`

  Commit: `git commit -am "feat: serve bounded review evidence"`

## Task 5: 配方卡片 sticky 证据体验

**Files:**
- Modify: `lite_app/static/review.js`
- Modify: `lite_app/static/style.css`
- Test: `tests_lite/test_review_api.py`
- Test: `tests_lite/test_web.py`

- [ ] **Step 1: 增加静态契约失败测试**

  断言证据图使用 crop URL、存在可聚焦“查看整图”链接、日期为文本输入、桌面 sticky、祖先无阻断 sticky 的 overflow、小于 900px 取消 sticky 且无嵌套滚动。

- [ ] **Step 2: 运行静态测试并确认 RED**

  Run: `.venv\Scripts\python.exe -m pytest tests_lite/test_review_api.py tests_lite/test_web.py -q`

- [ ] **Step 3: 实现桌面与窄屏布局**

  桌面约 42/58 两列；证据只在当前卡片范围内 sticky；圆角转移到内部标题/内容层；图片声明稳定 aspect ratio；窄屏证据置顶并取消 sticky；不显示“裁剪待确认”。

- [ ] **Step 4: 浏览器回归**

  在本地真实 Job 页检查 1440、800、375px：无横向滚动；长卡片滚动时当前证据可见；进入下一卡片自然切换；整图链接可键盘访问。

- [ ] **Step 5: 验证并提交 Task 5**

  Run: `.venv\Scripts\python.exe -m pytest tests_lite/test_review_api.py tests_lite/test_web.py -q`

  Commit: `git commit -am "feat: keep formula evidence visible during review"`

## Task 6: 全量验证、真实 Gate 与审计收口

**Files:**
- Modify: `docs/audits/PR9_REVIEW_REMEDIATION_WIP.md`
- Modify: `docs/superpowers/plans/2026-07-27-sticky-cropped-evidence-and-date-sorting.md`

- [ ] **Step 1: 全量自动化验证**

  Run:
  - `.venv\Scripts\python.exe -m ruff check lite_app tests_lite scripts`
  - `.venv\Scripts\python.exe -m pytest -m "not real_ocr" -q`
  - `git diff --check`
  - `git grep -n -E 'sk-(ws|sp)-[A-Za-z0-9._-]+'`
  - `git diff | Select-String -Pattern 'sk-(ws|sp)-[A-Za-z0-9._-]+'`

- [ ] **Step 2: 真实两图证据 Gate**

  对既有真实 Job 的两张原图建立新 Job，不覆盖旧证据。检查 7 条配方均绑定正确来源图，裁剪包含配方标题/序号、第二排日期、材料与数量，必要时包含工艺；失败项回退较大区域或整图。

- [ ] **Step 3: 用户确认 Gate**

  保持 Job 为 REVIEW_REQUIRED，交由用户逐条核对裁剪与日期原文。未经用户实际确认，不伪造 READY、知识写回或 Excel 成功。

- [ ] **Step 4: 更新审计报告**

  写入提交 SHA、测试数、Ruff、Secret 扫描、真实 Job 证据、日期样例、裁剪 manifest 与仍阻塞 Gate；顶部保留可直接复制给独立 GPT 的脱敏审查提示词。

- [ ] **Step 5: 推送 Draft PR**

  推送 `feat/personal-knowledge-layer`，确认 PR #9 仍为 Draft；禁止 merge、tag、release。

- [ ] **Step 6: 完成计划自审**

  将已完成 checkbox 更新为 `[x]`；执行占位文本扫描；核对设计文档每项要求均有代码、测试或明确用户 Gate 证据。
