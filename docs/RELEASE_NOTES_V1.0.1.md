# daily-record-ocr-lite v1.0.1

这是 Qwen3.7 Plus P0 热修复版本。

- 修复 qwen3.7-plus HTTP 200 被误判为 `FAILED_JSON_CAPABILITY`。
- 增加 JSON 围栏和嵌入 JSON 兼容。
- 分离视觉能力与 JSON 能力，并单独报告严格 JSON 能力。
- 默认关闭 qwen3.7 思考，使用阿里云兼容的 `json_object` 输出格式。
- 真实 DashScope 按量 API 验证通过：marker 为 `VISION-7319`，三项能力均为 true。
- Key 未进入 Git，公共 API 无法回读 Key。

本版本不包含 OCR 性能、多核、Mac 适配或 Pipeline 重构；这些工作进入 v1.0.2。
