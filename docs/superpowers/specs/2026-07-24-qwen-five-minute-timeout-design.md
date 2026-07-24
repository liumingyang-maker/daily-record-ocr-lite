# Qwen3.7 Plus 五分钟正式识别超时设计

## 目标

Token Plan 百炼端点的小型能力探针可以成功，但正式手写记录识别在 120 秒后超时。
本热修复只为阿里云兼容端点上的 `qwen3.7-plus` 将单次 HTTP 请求超时提高到至少
300 秒，并用真实完整识别结果判断模型是否真正理解任务。

## 范围

- 修改 `OpenAICompatibleVisionProvider` 的 Qwen3.7 Plus 请求策略。
- 阿里云域名且模型名为 `qwen3.7-plus` 时：
  - 保留 `response_format={"type":"json_object"}`；
  - 保留 `enable_thinking=false`；
  - 将小于 300 秒的配置超时提升到 300 秒。
- 已显式配置大于 300 秒时保留用户值。
- 非 Qwen3.7 Plus、非阿里云端点保持原超时。
- 不修改 OCR、预热、多核、Mac 适配、Pipeline、Schema 或 Prompt。

## 验收

### 自动化

先写失败测试，再实现：

1. 阿里云 `qwen3.7-plus` 配置 120 秒时，Provider 实际超时为 300 秒。
2. 阿里云 `qwen3.7-plus` 配置 420 秒时，Provider 保留 420 秒。
3. 其他模型配置 120 秒时仍为 120 秒。
4. 原有 Qwen 请求参数测试继续通过。

### 真实任务

使用失败任务 `20260724-201326-b247dd` 的同一张原图创建新任务，不覆盖原失败证据。
真实验收必须运行完整 OCR、Vision、JSON 提取、Schema 校验、Fusion 和 FinalResult
链路，不能只运行 marker 探针。

结果分类：

- 300 秒内完成且生成可查看、可导出的结构化结果：确认原超时阈值过短。
- 收到回复但 JSON、Schema 或字段语义失败：判定模型/Prompt 能力问题。
- 300 秒仍超时：判定 Token Plan 后端不适合该正式负载。
- HTTP 或鉴权失败：判定连接配置问题。

## 安全

- 不读取或输出 API Key 内容。
- 不记录 Authorization Header 或原始模型回复到审计报告。
- 真实任务产生的本机数据继续由 `.gitignore` 排除。
- 不提交真实图片、任务数据、日志或本机配置。
