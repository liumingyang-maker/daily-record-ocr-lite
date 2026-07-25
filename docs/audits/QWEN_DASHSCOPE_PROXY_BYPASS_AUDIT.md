# Qwen3.7 Plus DashScope 代理链路修复审计

## 可复制给 GPT 的独立审计请求

```text
请作为独立软件变更审计员，审查 daily-record-ocr-lite Draft PR #6
中新增的 DashScope Qwen3.7 Plus 环境代理绕过修复。

仓库：
https://github.com/liumingyang-maker/daily-record-ocr-lite

PR：
https://github.com/liumingyang-maker/daily-record-ocr-lite/pull/6

分支：
fix/qwen-record-schema-prompt

审计重点：
1. DashScope 域名 + qwen3.7-plus 是否默认使用 trust_env=false。
2. 显式 trust_env=true 是否仍可恢复环境代理。
3. 非目标 OpenAI 兼容端点是否保持 trust_env=true 的原行为。
4. 修复是否仅改变 HTTP 传输路径，没有修改 OCR、Schema、Fusion、
   FinalResult 或 Excel Gate。
5. 自动化测试是否真实覆盖传入 httpx.AsyncClient 的 trust_env 参数。
6. 真实两图完整任务是否收到 HTTP 200/content、完成 JSON 提取、
   Schema、FinalResult，并进入 REVIEW_REQUIRED。
7. Excel 未生成是否被如实归因为 105 个待人工核对字段，而不是网络失败。
8. 是否没有把 API Key、Authorization Header、原始响应、图片、Job 数据
   或本机配置提交到 Git。

请输出：
- 阻断/严重问题
- 重要问题
- P2 问题
- 规范符合性
- 是否建议 PR #6 从 Draft 转 Ready
- 是否建议合并

每项发现请提供文件和行号。不要输出或索取 API Key。
```

## 根因与单变量 A/B

运行应用的 Windows 进程同时存在 `HTTP_PROXY`、`HTTPS_PROXY` 和
`ALL_PROXY` 环境变量，均指向本机 `127.0.0.1:7890`。原实现使用
`httpx.AsyncClient()` 默认的 `trust_env=true`，因此 DashScope 请求会继承
该代理。

同一个两图完整业务请求只改变 `trust_env`：

| 路径 | 图片 | 请求体 | 结果 | 延迟 |
|---|---:|---:|---|---:|
| 原环境代理路径 | 2 / 404401 bytes | 约 554477 bytes | 响应头前断开 | 8–25 秒 |
| DashScope 直连路径 | 2 / 404401 bytes | 554477 bytes | HTTP 200 | 180975 ms |

直连结果：

- 收到响应头：是
- HTTP 状态：200
- request_id：服务返回，具体值未持久化
- 收到 content：是
- content 字符数：39803
- JSON 提取：通过
- Schema 致命错误：0
- 完整响应未写入公共日志或本审计

该 A/B 证明图片、完整 Prompt 和 Schema 能由同一按量端点处理；本机环境
代理是此前“Server disconnected without sending a response”的直接触发路径。

## 最小代码修复

`OpenAICompatibleVisionProvider` 现在：

- 对 `*.aliyuncs.com` + `qwen3.7-plus` 默认设置 `trust_env=false`。
- 允许配置显式 `trust_env=true` 恢复环境代理。
- 非目标端点默认仍为 `trust_env=true`。
- 把最终值传入 `httpx.AsyncClient`。

没有增加重试，没有继续延长超时，也没有修改 OCR、Prompt、Schema、
Fusion、FinalResult 或导出 Gate。

## TDD 与静态检查

RED：

- 新测试在旧实现上出现 3 个预期失败。
- 失败原因均为 `httpx.AsyncClient` 没有收到 `trust_env` 参数。

GREEN：

- DashScope Qwen 默认直连：通过。
- DashScope Qwen 显式使用环境代理：通过。
- 非目标端点保持环境代理：通过。
- DashScope 合约测试：`8 passed`。
- 全量非真实 OCR：`280 passed, 5 deselected`。
- Ruff：`All checks passed!`
- `git diff --check`：通过。

## 产品完整两图复验

新 Job：`20260725-170106-6407b0`

旧失败 Job 均保留，未覆盖或删除。

- 输入图片：2
- 状态：`REVIEW_REQUIRED`
- 错误：空
- OCR：成功，2 张均缓存命中，`2925 ms`
- Vision：真实按量 API，未命中缓存，`199097 ms`
- `vision/raw_response.txt`：已生成，仅保留在本机忽略目录
- `vision/structured_result.json`：已生成
- `vision/schema_errors.json`：空数组
- Schema：`VALID`
- Fusion：已生成
- `review/final_result.json`：已生成
- BusinessEntities：已生成

Recognition Gate 已通过。任务仍有 105 个字段需要人工核对，因此正式 Excel
导出端点按 fail-closed 设计返回 HTTP 400：

```text
正式导出仅允许 READY 任务；当前状态为 REVIEW_REQUIRED
```

本次没有把模型值批量伪装成 `MANUAL_CONFIRMED`，因此没有伪造 Export Gate
成功。用户完成字段核对并使任务进入 `READY` 后，才允许生成正式 Excel。

## 安全与发布边界

- 完整 API Key 未进入代码、测试、审计或 Git diff。
- 仓库扫描只命中已有示例占位符 `sk-ws-...`，真实 Key 命中为 0。
- `data/settings.json`、`data/secrets.env`、Job、图片、日志和原始响应均未进入
  分支。
- PR #6 保持 Draft。
- 不合并、不 Tag、不发布。

## 当前建议

网络 P0 已修复，真实两图 Recognition Gate 已通过。PR #6 是否转 Ready 应等待：

1. CI 对新增提交全绿；
2. 独立 GPT 审计没有阻断问题；
3. 用户决定是否把“人工核对后 Export Gate”作为本 PR 的合并前必要条件。

