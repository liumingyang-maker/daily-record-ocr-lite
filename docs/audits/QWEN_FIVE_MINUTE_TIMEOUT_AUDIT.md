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
- 审计日期：2026-07-24

## 变更

`OpenAICompatibleVisionProvider` 对阿里云域名的 `qwen3.7-plus`：

- 保留 `response_format={"type":"json_object"}`。
- 保留 `enable_thinking=false`。
- 实际超时使用 `max(configured_timeout, 300)`。
- 非目标模型仍使用原配置值。

未修改 OCR、预热、多核、Pipeline、Schema、Prompt、配置页面或平台安装层。

## TDD

- 基线：目标测试 `1 passed`；非 real_ocr 为 `249 passed, 5 deselected`。
- RED：`assert 120 == 300`，结果 `1 failed, 3 passed`。
- GREEN：目标测试 `4 passed`。
- 全量非 real_ocr：`252 passed, 5 deselected`。
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

## 当前结论

五分钟超时行为的代码与自动化 Gate 通过，但真实正式任务 Gate 失败，且失败发生在远端
无响应断开，不是客户端超时。可以创建带有失败证据的诊断 PR 供审查，但在正式任务
成功前不建议合并，更不得发布。
