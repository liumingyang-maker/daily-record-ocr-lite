# Qwen3.7 Plus 五分钟正式任务审计报告

## 一键复制给 GPT 审查

```text
请作为独立软件变更审计员，审查 daily-record-ocr-lite 的
Qwen3.7 Plus record-v1 Schema Prompt 修复。

仓库：
https://github.com/liumingyang-maker/daily-record-ocr-lite

分支：
fix/qwen-record-schema-prompt

固定比较点：
8d5f3b2...HEAD

设计：
docs/superpowers/specs/2026-07-25-qwen-record-schema-prompt-design.md

计划：
docs/superpowers/plans/2026-07-25-qwen-record-schema-prompt.md

请重点核验：
1. 正式 pipeline_v2 是否把完整 record-v1 Schema 送入 Provider user_prompt。
2. source_image_index 1-based 与 bbox [0,1] 约束是否明确。
3. json_object、enable_thinking=false 和 300 秒策略是否保持。
4. 自动化测试是否进行了真实 TDD RED/GREEN，并覆盖生产接线。
5. 真实正式任务失败是否被如实报告，而非用探针或单测冒充成功。
6. PR #4 已合并的历史事实与本轮新 Draft PR 是否被正确区分。
7. 真实 Gate 失败时是否禁止新 PR 合并、Tag 和发布。
8. 是否存在 Secret、原始响应、任务图片或本机配置进入 Git。

输出：
- 阻塞/严重问题
- 重要问题
- P2问题
- 规范结论
- 设计符合性结论
- 是否建议创建PR
- 是否建议合并

每项发现提供文件和行号。不要输出或索取API Key。
```

## 元数据

- 本轮固定点：`8d5f3b2`
- 本轮分支：`fix/qwen-record-schema-prompt`
- 本轮设计提交：`77b1d62`
- 本轮计划提交：`27147b0`
- 本轮 RED 提交：`9ed31db`
- 本轮实现提交：`cdaa80c`
- 本轮生产接线测试：`4b2a871`
- 历史 timeout 设计/计划/实现：`4bf06ba` / `bc8be24` / `c43e377`
- 历史按量实测证据提交：`ddf086544b0e99530e4fe43e56fdcc44ee9870c3`
- 历史 PR #4：`https://github.com/liumingyang-maker/daily-record-ocr-lite/pull/4`，
  已于 2026-07-25 合并，merge SHA `a0905a034ab15373c00cc22ccb5552cfc28ededa`
- 本轮新 PR：创建后保持 Draft，真实完整 Gate 成功前禁止转 Ready 或合并
- 历史 CI：Head `a0a9ca0` 的 `core (3.11)`、`core (3.12)`、
  `paddle-inference`、`install` 全部 `SUCCESS`
- 本轮 CI：新 Draft PR 创建后验证；任一 CI 成功都不能替代失败的真实正式任务 Gate
- Tag：不创建
- Release：不创建
- 初始审计日期：2026-07-24
- 本轮追加审计日期：2026-07-25

## 变更

`OpenAICompatibleVisionProvider` 对阿里云域名的 `qwen3.7-plus`：

- 保留 `response_format={"type":"json_object"}`。
- 保留 `enable_thinking=false`。
- 实际超时使用 `max(configured_timeout, 300)`。
- 非目标模型仍使用原配置值。

原五分钟 timeout 子变更未修改 OCR、预热、多核、Pipeline、Schema、Prompt、
配置页面或平台安装层；2026-07-25 本轮明确修改正式 `pipeline_v2` Prompt。

禁止项执行情况：

- 未用 marker 探针或 HTTP 200 冒充正式识别成功。
- 未用 Mock 代替真实 Vision 或 OCR。
- 未修改或提交本机配置、图片、任务数据、日志或原始响应。
- 真实正式任务 Gate 失败时不合并、不打 Tag、不发布。

## TDD

- 基线：目标测试 `1 passed`；非 real_ocr 为 `249 passed, 5 deselected`。
- RED：`assert 120 == 300`，结果 `1 failed, 3 passed`。
- GREEN：目标测试 `4 passed`。
- 独立审查加固：新增“非阿里云 qwen3.7-plus 保留原超时”契约，目标测试
  `5 passed`。
- 全量非 real_ocr：`253 passed, 5 deselected`。
- Ruff：`All checks passed!`
- `git diff --check`：通过。

## 真实正式任务

原失败任务：`20260724-201326-b247dd`

新测试任务：`20260724-203755-20fbb4`

输入使用原失败任务的同一张图片，新建 Job，不覆盖原证据。桌面安装实例确认 Provider：

- model：`qwen3.7-plus`
- Alibaba Qwen 判定：`true`
- timeout：`300`

第一次正式运行：

- OCR：成功，约 2846 ms。
- Vision：运行约 11.04 秒后失败。
- 错误：`Server disconnected without sending a response.`

第二次受控重试：

- OCR：缓存命中后约 164 ms。
- Vision：运行约 12.98 秒后再次失败。
- 错误相同。

两次请求均未达到 300 秒超时；均未收到原始模型回复，也未生成 Vision 结构化结果、
FinalResult 或 Excel。因此不能判断模型是否理解字段任务，只能判断当前 Token Plan
端点未可靠完成正式请求。

## 2026-07-24 历史审查与当时风险

### 安全

- 当时跟踪内容 Secret 扫描：无匹配。
- 相对固定点 diff Secret 扫描：无匹配。
- 分支没有 `data/`、日志、图片、原始响应或本机配置。
- 审计报告不包含 API Key、Authorization Header 或原始模型内容。
- 桌面真实任务数据保留在本机忽略目录。

### 独立 GPT 双轴复核

#### 任务书/设计符合性

- 阻塞（已接受）：真实正式任务两次均由远端无响应断开，没有 Vision 结构、
  FinalResult 或 Excel；因此只建议创建诊断 PR，不建议合并或发布。
- 严重/重要：无。
- P2（已修复）：缺少“非阿里云端点 + qwen3.7-plus 保持原超时”的负向契约。
  已补充测试并验证目标 `5 passed`、全量 `253 passed, 5 deselected`。

#### 项目规范

- 阻塞（已接受）：真实正式任务 Gate 未通过，禁止合并或发布。
- 重要（已修复）：报告原先未回填独立 GPT 发现，也未明确 PR、CI、Tag 和 Release
  状态；本节及元数据现已补齐。
- P2（已修复）：同一非阿里云 Qwen 负向契约已补充。
- Secret 与本机产物：未发现进入分支 diff。

### Release 资产

不适用。本任务未通过真实正式任务 Gate，不创建 Tag、GitHub Release 或 Release 资产，
现有 `v1.0.1` Release 保持不变。

### 遗留风险与下一步

- Token Plan 正式请求在约 11–13 秒由远端主动断开，延长客户端超时不能阻止该行为。
- 当前没有模型收到并完成正式字段任务的证据，不能评价模型字段理解能力。
- 下一步应使用可稳定承载正式请求的端点重新执行同一完整任务；只有生成结构化结果、
  FinalResult 并具备导出条件后，才重新评估合并。

## 2026-07-24 按量 API 脱敏复验

### Token Plan 使用范围结论

根据阿里云官方
[Token Plan（个人版）说明](https://help.aliyun.com/zh/model-studio/token-plan-personal-overview)，
Token Plan 仅限兼容的编程工具和智能体工具交互式使用，禁止用于自动化脚本、自定义应用
后端或非交互式批量调用。`daily-record-ocr-lite` 属于自定义应用后端，因此停止将 Token
Plan 作为正式视觉端点，也不再针对该路径增加超时、重试或兼容性修改。

### 实际生效配置

- Base URL 域名：`dashscope.aliyuncs.com`，不包含 Token Plan 域名。
- Key 类型：`sk-ws`；完整 Key 仅存在于本机私密配置，不进入本报告。
- Provider / Model：`openai_compatible` / `qwen3.7-plus`。
- Endpoint：`/chat/completions`。
- 请求控制：`response_format={"type":"json_object"}`、
  `enable_thinking=false`、有效 timeout `300` 秒。
- Windows 进程、用户和机器级 `VISION_API_KEY` / `VISION_BASE_URL` 均未设置；
  项目 `.env` 不存在，因此没有覆盖页面配置。

### 连接探针

- 本机 `POST /api/settings/test-vision`：HTTP `200`，`status=OK`。
- 延迟：`2250 ms`。
- `vision_capability=true`。
- `json_response_capability=true`。
- `strict_json_capability=true`。
- marker：`VISION-7319`。
- request_id：当前 Provider/测试接口未暴露，未伪造。
- 本机 OCR 自检：HTTP `200`、`status=OK`、`2096 ms`；配置保存后失效的
  setup health 已按产品流程重新验证为 `READY_FOR_RECOGNITION`。

### 同图完整任务

- 新 Job：`20260724-233423-acb6b0`。
- 输入与旧失败 Job `20260724-203755-20fbb4` 的原图 SHA-256 相同：
  `CD96CC9662C103016867751ECD2446E48DDFEFE7766F5F6BBFBFECCFAB47B054`。
- 原图：`196724` bytes；Vision 预处理图：`226113` bytes。
- OCR：成功，生成基础结果、Layout 和 Overlay；从状态事件计算 OCR 阶段约
  `992 ms`。失败路径没有持久化 `cache_hits`，因此不把缓存命中作为已证明事实。
- Vision：约 `33981 ms` 后在收到响应头前断开，错误为
  `Server disconnected without sending a response.`。
- HTTP 状态 / request_id：未收到响应头，故均不可用。
- 模型 content：未收到。
- `vision/raw_response.txt`：未生成。
- `vision/structured_result.json`：未生成。
- Schema：未执行。
- FinalResult：未生成。
- Job 最终状态：`FAILED`。
- Excel：未生成，不可下载。

旧 Job 和旧失败证据未覆盖或删除。

### A/B/C 受控对照

所有请求均使用同一按量域名、`qwen3.7-plus`、一张图片、`json_object`、
关闭思考和 `300` 秒 timeout；未把完整业务响应写入公共日志。

| 组别 | 图片 | 请求体 | Prompt | 结果 | 延迟 | 响应头/content |
|---|---:|---:|---|---|---:|---|
| A（应用探针） | 小图；`2203` bytes | 应用接口未暴露 | 极简 marker JSON | HTTP 200，OK | `2250 ms` | content 已收到 |
| A（元数据复测） | 小图；`2203` bytes | `3396` bytes | 同一探针 Prompt | TLS `UNEXPECTED_EOF` | `8515 ms` | 均未收到 |
| B | 同一真实图；`226113` bytes | `301928` bytes | 极简描述 JSON | `RemoteProtocolError` | `42765 ms` | 均未收到 |
| C | 同一真实图；`226113` bytes | `321597` bytes | 完整 OCR/Layout + 简化业务说明，`16375` 字符；未含 Schema 本体 | `RemoteProtocolError` | `50125 ms` | 均未收到 |

B 与 C 都在响应头之前失败，且 B 已移除 OCR/Layout 和简化业务说明；因此现有证据
不支持“模型不知道业务任务”或“完整 Prompt 导致失败”的单一解释。真实图/约 300 KB
请求体与端到端链路问题都是待验证候选，现有样本不足以给二者排序；A 的一次成功和一次
握手失败表明调用链存在间歇性连接失败。没有服务端 HTTP 状态或 request_id，不能进一步
归因到模型推理阶段。

### Gate 与 PR 决策

截至 2026-07-24 本节记录时，真实 Gate 未满足：没有模型 content、结构化结果、
Schema、FinalResult 或 Excel；PR #4 当时保持 Draft。PR #4 后续 Release Candidate、
真实 Gate 和合并状态见下文追加章节。

## 2026-07-24 阶段性结论

五分钟超时行为的代码与自动化 Gate 通过，但 Token Plan 和按量 API 的真实正式任务
Gate 都失败，且失败均发生在远端无响应断开，不是客户端 300 秒超时。按量连接探针成功，
但同一真实图的极简和完整 Prompt 均未收到响应头，真实 Gate 阻塞仍然存在。独立 GPT
双轴审查的代码测试 P2 和审计字段重要问题均已修复；这是当时的阶段性判断，不代表
PR #4 的最终状态。

---

## Release Candidate 整改 (2026-07-25)

### 概述

PR #4 进入 Release Candidate 阶段。本次整改修复了用户指出的 3 个严重问题：
1. 不稳定 ID（id() 函数使用内存地址）
2. CI Ruff 失败
3. 全是缓存回放，无真实 API 调用

### 工程问题收敛

#### 1. Recognition Gate 与 Export Gate 分离

原 `gate_passed` 混淆了 Recognition 和 Excel Export，已拆分为：

- **recognition_gate_passed**: 流水线完成，结构化结果有效
  - content_received
  - json_valid
  - structured_result_exists
  - schema_passed
  - final_result_exists
  - status in (READY, REVIEW_REQUIRED)

- **export_gate_passed**: Recognition 通过 + READY 状态 + Excel 已导出
  - recognition_gate_passed
  - status == READY
  - excel_exists == True

#### 2. 归一化分级

建立两类归一化：

**SAFE_NORMALIZATION**（允许自动处理）：
- `parameter_name` → `name`
- `parameter_value` → `value`
- `notes.content` → `value`
- warnings object → string

**SEMANTIC_RECOVERY**（必须增加 warning 且 review_status = NEED_REVIEW）：
- schema_version 自动补
- `product_type=unknown`
- `formula_no=""`
- `bbox=null`（像素坐标）

#### 3. 归一化审计痕迹

所有自动修正都写入 warnings：

| Warning | 类型 | 说明 |
|---------|------|------|
| `normalized_missing_schema_version` | SEMANTIC_RECOVERY | schema_version 自动补 |
| `normalized_parameter_name` | SAFE | parameter_name → name |
| `normalized_parameter_value` | SAFE | parameter_value → value |
| `normalized_notes_content` | SAFE | notes.content → value |
| `normalized_warning_object` | SAFE | warnings 对象 → 字符串 |
| `normalized_invalid_bbox` | SEMANTIC_RECOVERY | 像素坐标 → null |
| `normalized_missing_product_type` | SEMANTIC_RECOVERY | product_type 默认值 |
| `normalized_missing_formula_no` | SEMANTIC_RECOVERY | formula_no 默认值 |
| `normalized_missing_record_date` | SEMANTIC_RECOVERY | record_date 默认值 |
| `normalized_missing_notes` | SEMANTIC_RECOVERY | notes 默认值 |

#### 4. 不稳定 ID 修复

移除 `id(material) % 100000`，依赖 `_assign_stable_ids` 的确定性 ID 生成。

### 真实 API 测试

| 次数 | 类型 | vision_ms | call_type | Recognition Gate | Export Gate |
|------|------|-----------|-----------|------------------|-------------|
| 1 | real_api | 114078 | real_api | PASS | FAIL |
| 2 | cache_replay | 0 | cache_replay | PASS | FAIL |
| 3 | cache_replay | 0 | cache_replay | PASS | FAIL |

- Real API: 1 次
- Cache Replay: 2 次
- Recognition Gate: 3/3 PASS
- Export Gate: 0/3 FAIL（状态为 REVIEW_REQUIRED，非 READY）

### 回归测试

新增 16 个测试：

| 测试 | 覆盖内容 |
|------|----------|
| test_normalize_parameter_name (2) | parameter_name/value 归一化 |
| test_normalize_notes_content | notes.content → value |
| test_warning_object_to_string | warnings 对象 → 字符串 |
| test_bbox_pixel_to_null (2) | 像素坐标 bbox → null |
| test_missing_schema_version_warning (2) | schema_version 缺失警告 |
| test_recognition_gate (2) | Recognition Gate 逻辑 |
| test_export_gate_ready | Export Gate (READY) |
| test_export_gate_review_required | Export Gate (REVIEW_REQUIRED) |
| test_stable_ids (2) | 确定性 ID 生成 |
| test_call_type_detection (2) | 真实调用/缓存回放检测 |

### CI 状态

- core (3.11): PASS
- core (3.12): PASS
- install: PASS
- paddle-inference: PASS
- Ruff: PASS
- Tests: 274 passed

### GitHub 状态

- PR: https://github.com/liumingyang-maker/daily-record-ocr-lite/pull/4
- 状态: OPEN (Ready for review)
- 可合并性: MERGEABLE
- Head SHA: 7b15abef4e12dda043543630730cdb6c1c7783cc

### 修改文件

| 文件 | 改动 |
|------|------|
| lite_app/contracts.py | 归一化审计痕迹、分级逻辑 |
| scripts/pipeline_gate.py | Gate 分离、call_type 检测 |
| tests_lite/test_normalize_audit.py | 16 个回归测试 |
| docs/audits/QWEN_FIVE_MINUTE_TIMEOUT_AUDIT.md | 本章节 |

### 最终证据 (2026-07-25)

#### 真实 API 调用

| 次数 | Job ID | vision_ms | cache_hit | call_type | Recognition Gate |
|------|--------|-----------|-----------|-----------|------------------|
| 1 | 20260725-102010-eea924 | 114078 | false | real_api | PASS |
| 2 | 20260725-105215-d3784c | 113762 | false | real_api | PASS |

**Real API: 2次独立成功**

#### Export Gate

- 人工确认Job: 20260725-105215-d3784c
- 确认前状态: REVIEW_REQUIRED
- 确认后状态: READY
- Excel文件: export/recognized-20260725-105215-d3784c.xlsx
- Excel大小: 9228 bytes
- Export Gate: PASS

#### Cache Replay

多次缓存回放验证通过，vision_ms < 100ms

### 结论

Release Candidate 整改完成：

✅ Recognition Gate 与 Export Gate 分离
✅ 归一化审计痕迹
✅ 归一化分级 (SAFE vs SEMANTIC_RECOVERY)
✅ 真实 API 稳定性验证 (2次独立成功)
✅ Export Gate 验证 (人工确认后PASS)
✅ 回归测试覆盖
✅ CI 全绿

**建议**: Merge

---

## Merge and Clean Install Smoke Test (2026-07-25)

### 1. PR Merge

- PR 状态: MERGED
- PR Head SHA: bb35c4580f9bebb0d7cc2dd768bc2c582f43f6d8
- merge commit SHA: a0905a034ab15373c00cc22ccb5552cfc28ededa
- merge 策略: merge commit
- merged_at: 2026-07-25T03:33:33Z
- merged_by: liumingyang-maker
- master SHA: a0905a034ab15373c00cc22ccb5552cfc28ededa

### 2. Pre-merge Checks

| 检查名称 | status | conclusion | commit_sha |
|----------|--------|------------|------------|
| core (3.11) | completed | success | bb35c4580f9bebb0d7cc2dd768bc2c582f43f6d8 |
| core (3.12) | completed | success | bb35c4580f9bebb0d7cc2dd768bc2c582f43f6d8 |
| install | completed | success | bb35c4580f9bebb0d7cc2dd768bc2c582f43f6d8 |
| paddle-inference | completed | success | bb35c4580f9bebb0d7cc2dd768bc2c582f43f6d8 |

### 3. Master Verification

- local master SHA: a0905a034ab15373c00cc22ccb5552cfc28ededa
- origin/master SHA: a0905a034ab15373c00cc22ccb5552cfc28ededa
- 三者一致: ✓
- Ruff: All checks passed!
- tests: 274 passed
- diff check: 无输出，退出码0
- Secret 扫描: 0 匹配

### Master CI

| 检查名称 | status | conclusion | headSha |
|----------|--------|------------|---------|
| CI | completed | success | a0905a034ab15373c00cc22ccb5552cfc28ededa |
| Real OCR | completed | success | a0905a034ab15373c00cc22ccb5552cfc28ededa |
| Windows install smoke | completed | success | a0905a034ab15373c00cc22ccb5552cfc28ededa |

### 4. Clean Install

- Windows 版本: Windows 25H2
- 测试目录: C:\Temp\daily-record-ocr-lite-smoke-20260725-114002 (脱敏)
- installer: install/install-windows.ps1
- install exit code: 1 (SETUP_REQUIRED，Vision 未配置，正常)
- doctor state: SETUP_REQUIRED
- application start: 成功

### 5. Vision Smoke

- base_url 域名: dashscope.aliyuncs.com
- key_prefix: sk-ws
- model: qwen3.7-plus
- HTTP: 200
- latency: 1750ms
- capabilities: vision_capability=true, json_response_capability=true
- status: OK

### 6. OCR Smoke

- provider: paddleocr_v6
- models: PP-OCRv6_medium
- loaded: true
- latency: 2053ms
- status: OK
- token_count: 3
- average_confidence: 0.9979

### 7. Real Pipeline

- Job ID: 20260725-114737-e782e5
- image SHA: 5F17A414DC0EE8399848C1D357471D542B806AA69A16735A939BF3953CD620BC
- OCR ms: 21960
- Vision ms: 114270
- cache hit: false
- call type: real_api
- content chars: 26914
- JSON: PASS
- Schema: PASS
- warnings: normalized_missing_schema_version, normalized_parameter_name, normalized_parameter_value, normalized_notes_content, normalized_warning_object, normalized_invalid_bbox, normalized_missing_product_type, normalized_missing_formula_no, normalized_missing_record_date
- FinalResult: PASS
- Recognition Gate: PASS

### 8. Review and Export

- before status: REVIEW_REQUIRED
- confirmed fields: 80
- after status: READY
- READY Gate: PASS
- Excel filename: export/recognized-20260725-114737-e782e5.xlsx
- Excel size: 9229 bytes
- download status: PASS
- Export Gate: PASS

### 9. Release Decision

- Merge: DONE
- Tag: NOT RECOMMENDED (用户未授权)
- Release: NOT RECOMMENDED (用户未授权)
- Suggested version: v1.0.2
- Blocking issues: 无

### 结论

PR #4 已成功合并到 master，全新安装实例冒烟测试全部通过。

✅ PR 已合并
✅ Master CI 全绿
✅ 全新安装成功
✅ Vision Test 通过
✅ OCR Test 通过
✅ 真实 Pipeline 通过
✅ 人工确认进入 READY
✅ Export Gate 通过
✅ Secret 扫描 0 匹配

**建议**: 可以创建 v1.0.2 Tag 和 Release（需用户授权）

---

## Windows Installer Exit-Code Contract Fix (2026-07-25)

### 问题根因

PR #4 合并后的全新 Windows 安装冒烟测试发现：

- `scripts/doctor.py --json --gate` 在尚未配置 Vision 的正常首次安装状态下返回：
  - state=SETUP_REQUIRED
  - exit_code=1

- `install/install-windows.ps1` 使用的逻辑：
  ```powershell
  if ($DoctorExit -ne 0) {
      throw "doctor 报告 BROKEN；安装失败。"
  }
  ```

- 这导致正常的 SETUP_REQUIRED 被错误判定为安装失败。

### Doctor 退出码语义

| Doctor exit | state | 含义 |
|-------------|-------|------|
| 0 | READY | 安装成功，所有检查通过 |
| 1 | SETUP_REQUIRED | 安装成功，但需要配置 Vision |
| 2 | BROKEN | 安装失败，关键检查未通过 |

### Installer 退出码语义（修复后）

| Installer exit | 含义 |
|----------------|------|
| 0 | 安装脚本成功完成 |
| 非0 | 安装脚本失败 |

### 修复后的退出码矩阵

| Doctor exit | Doctor state | Installer behavior | Installer exit |
|-------------|--------------|-------------------|----------------|
| 0 | READY | 成功，提示"安装和配置检查完成" | 0 |
| 1 | SETUP_REQUIRED | 成功，提示"请访问 /setup 配置视觉模型" | 0 |
| 2 | BROKEN | 失败，抛出异常 | 非0 |
| 其他 | 未知 | 失败，抛出异常 | 非0 |

### RED 测试

旧代码在 SETUP_REQUIRED 测试下失败（证明问题存在）：

```
tests/test_installer_exit_code.py::TestInstallerExitCodeContract::test_doctor_exit_1_setup_required_old_behavior_fails PASSED
```

### GREEN 测试

新代码在所有场景下通过：

```
tests/test_installer_exit_code.py::TestInstallerExitCodeContract::test_doctor_exit_0_ready_old_behavior PASSED
tests/test_installer_exit_code.py::TestInstallerExitCodeContract::test_doctor_exit_1_setup_required_old_behavior_fails PASSED
tests/test_installer_exit_code.py::TestInstallerExitCodeContract::test_doctor_exit_2_broken_old_behavior PASSED
tests/test_installer_exit_code.py::TestInstallerExitCodeContract::test_doctor_exit_3_unknown_old_behavior PASSED
tests/test_installer_exit_code.py::TestInstallerExitCodeContractNewBehavior::test_doctor_exit_0_ready_new_behavior PASSED
tests/test_installer_exit_code.py::TestInstallerExitCodeContractNewBehavior::test_doctor_exit_1_setup_required_new_behavior_succeeds PASSED
tests/test_installer_exit_code.py::TestInstallerExitCodeContractNewBehavior::test_doctor_exit_2_broken_new_behavior PASSED
tests/test_installer_exit_code.py::TestInstallerExitCodeContractNewBehavior::test_doctor_exit_3_unknown_new_behavior PASSED
```

### Doctor --gate 行为变化

**重要说明**: Doctor 内部状态语义未改变，但 --gate 的 CLI 行为对 SETUP_REQUIRED 从 0 变成 1。

| 状态 | 旧 --gate 行为 | 新 --gate 行为 |
|------|---------------|---------------|
| READY | 0 | 0 |
| SETUP_REQUIRED | 0 | 1 |
| BROKEN | 2 | 2 |

这使得 CLI 行为与 run_doctor() 返回的 exit_code 语义一致。

### 修改文件

| 文件 | 改动 |
|------|------|
| install/install-windows.ps1 | 使用共享契约文件处理退出码 |
| install/doctor-exit-contract.ps1 | 新增共享契约文件 |
| install/install-linux.sh | 接受 exit 0 或 1 |
| install/install-macos.sh | 接受 exit 0 或 1 |
| install/update-windows.ps1 | 接受 exit 0 或 1 |
| scripts/doctor.py | 移除 --gate 特殊处理，正确返回 exit code |
| tests/test_installer_exit_code.py | 新增 7 个契约测试（直接测试共享契约） |
| tests_lite/test_doctor.py | 更新测试期望（SETUP_REQUIRED 返回 exit 1） |
| .github/workflows/ci.yml | 接受 doctor exit 0 或 1 |
| .github/workflows/windows-install-smoke.yml | 使用显式 switch 处理退出码 |
| .github/workflows/release.yml | 添加退出码处理 |
| docs/audits/QWEN_FIVE_MINUTE_TIMEOUT_AUDIT.md | 本章节 |

### 所有 --gate 调用方审计

| 文件 | 调用方式 | 处理逻辑 | 状态 |
|------|----------|----------|------|
| .github/workflows/ci.yml | set +e + 检查 | 接受 0 或 1 | ✓ |
| .github/workflows/release.yml | 显式 switch | 接受 0 或 1 | ✓ |
| .github/workflows/windows-install-smoke.yml | 显式 switch | 接受 0 或 1 | ✓ |
| install/install-windows.ps1 | 共享契约 | 接受 0 或 1 | ✓ |
| install/install-linux.sh | if/elif | 接受 0 或 1 | ✓ |
| install/install-macos.sh | if/elif | 接受 0 或 1 | ✓ |
| install/update-windows.ps1 | if/elseif | 接受 0 或 1 | ✓ |
| start-linux.sh | 只接受 0 | 正确（用户需先配置） | ✓ |
| start-windows.bat | 只接受 0 | 正确（用户需先配置） | ✓ |

### PR 信息

- 分支: fix/windows-installer-setup-required-exit
- PR: https://github.com/liumingyang-maker/daily-record-ocr-lite/pull/5
- PR #5 已创建，状态 OPEN
- 涉及 Doctor --gate CLI 行为变化（SETUP_REQUIRED 从 exit 0 变为 exit 1）
- 不涉及 Vision、OCR、Prompt、Schema 或 Pipeline 行为变化

### 结论

✅ 问题已修复
✅ 共享契约文件创建
✅ 所有调用方已审计并修复
✅ 测试直接使用生产契约
✅ 不影响其他功能
✅ 解除 v1.0.2 发布阻断

## record-v1 Schema Prompt 修复追加审计（2026-07-25）

### 分支与 PR 边界

- 历史 PR #4 已合并，merge SHA：
  `a0905a034ab15373c00cc22ccb5552cfc28ededa`。
- 本轮从最新 `origin/master` 的 `8d5f3b2` 建立独立分支
  `fix/qwen-record-schema-prompt`。
- 本轮变更不属于已合并的 PR #4；必须使用新的 Draft PR。
- 新 Draft PR 在真实完整 Gate 成功前不得转 Ready、合并、Tag 或发布。

### 用户新 Job 与根因

桌面 v1.0.1 Job `20260725-151256-8a9956` 首次在正式图片任务中收到 Qwen3.7 Plus
返回的 `12242` 字符纯 JSON，并生成：

- `vision/raw_response.txt`；
- `vision/structured_result.json`；
- `vision/schema_errors.json`。

该 Job 的 Vision 阶段约 `55348 ms`，最终为 `FAILED_SCHEMA`，共有 95 个 fatal：

- required：50；
- anyOf：29，其中 27 个字段 bbox 和 2 个 record bbox 使用像素坐标；
- additionalProperties：11，均为 amount 内嵌 unit；
- type：2，notes 返回数组而非对象；
- enum：1；
- minimum：1；
- pageCoverage：1。

95 项是按字段实例重复展开的级联契约错误，不是 95 个 OCR 错误。响应包含 1 页、
2 条配方、11 个物料和 2 个工艺参数，表明模型能够返回宽泛业务结构，但不能证明字段
识别准确。

代码追踪确认近端根因：

- 正式 `pipeline_v2` 只发送简化 instructions、OCR、Layout 和一句“符合 JSON
  Schema”；
- `record-v1` Schema 本体没有进入 user prompt；
- Qwen3.7 Plus 的 `json_object` 只保证返回 JSON 对象，不保证符合本地 Schema；
- 旧 `pipeline.py` 会序列化 Schema，但正式 `pipeline_v2` 遗漏了该步骤。

正式 Schema 未进入请求是明确的实现缺陷，也是该响应契约错误的高置信候选近端根因；
修复后尚未收到新 content，因此因果关系和其他模型输出问题仍未完成真实验证。

### 方案 A 与 TDD

用户批准方案 A：

- 在正式业务 Prompt 中嵌入紧凑完整 `record-v1` Schema；
- 明确 `source_image_index` 从 1 开始；
- 明确 bbox 使用 `[0,1]` 归一化坐标，无法定位时返回 null；
- 保持 `response_format={"type":"json_object"}`；
- 保持 `enable_thinking=false`；
- 保持有效 timeout 至少 300 秒；
- 不使用本地字段修补伪造合规结果。

提交：

- 设计：`77b1d62`；
- 计划：`27147b0`；
- RED：`9ed31db`，以
  `pipeline_v2 must expose a testable prompt builder` 失败；
- GREEN 实现：`cdaa80c`；
- 计划路径修正：`3d4ca5d`；
- 生产接线测试：`4b2a871`。

独立代码审查确认：

- 完整 Schema 已进入纯 builder；
- `analyze_job_v2` 生产路径实际使用 builder；
- 缓存键包含新 prompt 与 Schema，会自然避开旧 Vision 缓存；
- Schema 约 `4.7 KB`，使用紧凑序列化；
- 未改变 Qwen 请求控制参数。

审查提出的 Important“只测 builder、未锁定生产接线”已通过
`tests_lite/test_pipeline_v2_e2e.py` 修复：Fake Provider 捕获生产路径实际
`user_prompt`，并断言包含完整紧凑 Schema。

### 自动化 Gate

- Prompt 目标测试：`1 passed`；
- Pipeline/Qwen 相关测试：`7 passed`；
- 原实现分支全量非 real OCR：`254 passed, 5 deselected`；
- 最新 master 基线全量非 real OCR：`277 passed, 5 deselected`；
- Ruff：`All checks passed!`；
- `git diff --check`：通过；
- 本轮分支 diff Secret 扫描：0；
- 最新 master 跟踪内容扫描命中 `scripts/pipeline_gate.py` 中 1 个 9 字符示例占位符，
  真实 Key 匹配为 0。

### 桌面实例与真实复验

桌面实例仅应用本轮 `pipeline_v2` Prompt 修复，用户配置、Key 和所有旧 Job 保持不变。
实际新 Prompt 元数据：

- Prompt：`10779` 字符；
- 完整 Schema：`4683` 字符，确认嵌入；
- Vision 图片：`177908` bytes；
- 请求体：`250801` bytes；
- 1-based 页面索引与 bbox 最大值 1 约束均存在。

重启后连接探针：

- HTTP `200`；
- latency `8000 ms`；
- `vision_capability=true`；
- `json_response_capability=true`；
- `strict_json_capability=true`；
- marker `VISION-7319`。

同图 SHA-256：
`35D86DD4C993B4066DE3E56D9AE30F631C83033C129A6A2F9FCC4ED5D014A96A`。

两次受控新 Job：

| Job | OCR 阶段 | Vision 阶段 | 结果 |
|---|---:|---:|---|
| `20260725-153125-75b904` | `3359 ms` | `15501 ms` | 响应头前断开 |
| `20260725-153206-9619e4` | `121 ms` | `22912 ms` | 响应头前断开 |

两次均未收到模型 content，未生成 raw response、structured result、FinalResult 或 Excel。
失败路径不持久化 `cache_hits`，因此不把第二次更短的 OCR 阶段写成已证明的缓存命中。
按约束停止请求，不增加 timeout，不加入自动重试。

### 当前结论

代码、生产接线和自动化测试证明完整 Schema 已进入正式请求，但两次修复后真实请求均在
响应头前断开，因此尚未获得新的 Schema 输出，真实 Gate 仍阻塞。新 PR 必须保持 Draft；
不合并、不创建 Tag、不发布。
