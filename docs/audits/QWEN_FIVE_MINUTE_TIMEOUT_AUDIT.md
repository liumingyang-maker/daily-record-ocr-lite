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
- PR：`https://github.com/liumingyang-maker/daily-record-ocr-lite/pull/4`（Draft/诊断）
- CI：运行中；即使通过也不能替代失败的真实正式任务 Gate
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

## 当前结论

五分钟超时行为的代码与自动化 Gate 通过，但真实正式任务 Gate 失败，且失败发生在远端
无响应断开，不是客户端超时。独立 GPT 双轴审查的代码测试 P2 和审计字段重要问题均
已修复；真实 Gate 阻塞仍然存在。可以创建带有失败证据的 Draft/诊断 PR 供 CI 和审查，
但在正式任务成功前不建议合并，更不得发布。
