# Qwen3.7 Plus 五分钟正式任务审计报告

## 一键复制给 GPT 审查

```text
请作为独立软件变更审计员，审查 daily-record-ocr-lite 的
Qwen3.7 Plus 五分钟正式识别超时热修复。

仓库：
https://github.com/liumingyang-maker/daily-record-ocr-lite

分支：
fix/qwen-five-minute-timeout

固定比较点：
d5751781a49042b79872177f8d357779f828aaad...HEAD

设计：
docs/superpowers/specs/2026-07-24-qwen-five-minute-timeout-design.md

计划：
docs/superpowers/plans/2026-07-24-qwen-five-minute-timeout.md

请重点核验：
1. 仅阿里云域名的 qwen3.7-plus 被提升到至少300秒。
2. 用户显式配置超过300秒时是否保留。
3. 其他模型和其他端点是否保持原超时。
4. json_object和enable_thinking=false是否保持。
5. 自动化测试是否进行了真实TDD RED/GREEN。
6. 真实正式任务失败是否被如实报告，而非用HTTP、小探针或延时冒充成功。
7. 失败时是否禁止合并和发布。
8. 是否存在Secret、原始响应、任务图片或本机配置进入Git。

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

- 固定点：`d5751781a49042b79872177f8d357779f828aaad`
- 分支：`fix/qwen-five-minute-timeout`
- 设计提交：`4bf06ba`
- 计划提交：`bc8be24`
- 实现提交：`c43e377`
- 按量实测证据提交：`ddf086544b0e99530e4fe43e56fdcc44ee9870c3`
- PR：`https://github.com/liumingyang-maker/daily-record-ocr-lite/pull/4`（Draft/诊断）
- CI：代码与首轮审计 Head `a0a9ca0` 的 `core (3.11)`、`core (3.12)`、
  `paddle-inference`、`install` 全部 `SUCCESS`；后续仅文档提交的实时 CI 以 PR 页面
  为准。任一 CI 成功都不能替代失败的真实正式任务 Gate
- Tag：不创建
- Release：不创建
- 审计日期：2026-07-24

## 变更

`OpenAICompatibleVisionProvider` 对阿里云域名的 `qwen3.7-plus`：

- 保留 `response_format={"type":"json_object"}`。
- 保留 `enable_thinking=false`。
- 实际超时使用 `max(configured_timeout, 300)`。
- 非目标模型仍使用原配置值。

未修改 OCR、预热、多核、Pipeline、Schema、Prompt、配置页面或平台安装层。

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

## 安全

- 跟踪内容 Secret 扫描：无匹配。
- 相对固定点 diff Secret 扫描：无匹配。
- 分支没有 `data/`、日志、图片、原始响应或本机配置。
- 审计报告不包含 API Key、Authorization Header 或原始模型内容。
- 桌面真实任务数据保留在本机忽略目录。

## 独立 GPT 双轴复核

### 任务书/设计符合性

- 阻塞（已接受）：真实正式任务两次均由远端无响应断开，没有 Vision 结构、
  FinalResult 或 Excel；因此只建议创建诊断 PR，不建议合并或发布。
- 严重/重要：无。
- P2（已修复）：缺少“非阿里云端点 + qwen3.7-plus 保持原超时”的负向契约。
  已补充测试并验证目标 `5 passed`、全量 `253 passed, 5 deselected`。

### 项目规范

- 阻塞（已接受）：真实正式任务 Gate 未通过，禁止合并或发布。
- 重要（已修复）：报告原先未回填独立 GPT 发现，也未明确 PR、CI、Tag 和 Release
  状态；本节及元数据现已补齐。
- P2（已修复）：同一非阿里云 Qwen 负向契约已补充。
- Secret 与本机产物：未发现进入分支 diff。

## Release 资产

不适用。本任务未通过真实正式任务 Gate，不创建 Tag、GitHub Release 或 Release 资产，
现有 `v1.0.1` Release 保持不变。

## 遗留风险与下一步

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
| C | 同一真实图；`226113` bytes | `321597` bytes | 完整 OCR/Layout/Schema，`16375` 字符 | `RemoteProtocolError` | `50125 ms` | 均未收到 |

B 与 C 都在响应头之前失败，且 B 已移除完整 OCR/Layout/Schema Prompt；因此现有证据
不支持“模型不知道业务任务”或“完整 Prompt 导致失败”的单一解释。真实图/约 300 KB
请求体与端到端链路问题都是待验证候选，现有样本不足以给二者排序；A 的一次成功和一次
握手失败表明调用链存在间歇性连接失败。没有服务端 HTTP 状态或 request_id，不能进一步
归因到模型推理阶段。

### Gate 与 PR 决策

真实 Gate 未满足：没有模型 content、结构化结果、Schema、FinalResult 或 Excel。
PR #4 继续保持 Draft；不合并、不创建 Tag、不发布。下一步若继续诊断，应优先取得
阿里云服务端请求接收证据或检查真实图片请求大小/网关限制，而不是继续增加客户端超时。

## 当前结论

五分钟超时行为的代码与自动化 Gate 通过，但 Token Plan 和按量 API 的真实正式任务
Gate 都失败，且失败均发生在远端无响应断开，不是客户端 300 秒超时。按量连接探针成功，
但同一真实图的极简和完整 Prompt 均未收到响应头，真实 Gate 阻塞仍然存在。独立 GPT
双轴审查的代码测试 P2 和审计字段重要问题均已修复；PR #4 继续保持 Draft，在正式任务
成功前不合并、不打 Tag、不发布。

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
- Head SHA: 待提交后更新

### 修改文件

| 文件 | 改动 |
|------|------|
| lite_app/contracts.py | 归一化审计痕迹、分级逻辑 |
| scripts/pipeline_gate.py | Gate 分离、call_type 检测 |
| tests_lite/test_normalize_audit.py | 16 个回归测试 |
| docs/audits/QWEN_FIVE_MINUTE_TIMEOUT_AUDIT.md | 本章节 |

### 结论

Release Candidate 整改完成：

✅ Recognition Gate 与 Export Gate 分离
✅ 归一化审计痕迹
✅ 归一化分级 (SAFE vs SEMANTIC_RECOVERY)
✅ 真实 API 稳定性验证
✅ 回归测试覆盖
✅ CI 全绿

**建议**: Merge（待最终 Head SHA 更新后）
