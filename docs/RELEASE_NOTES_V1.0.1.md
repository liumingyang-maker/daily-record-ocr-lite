# daily-record-ocr-lite v1.0.1

这是 Qwen3.7 Plus P0 热修复版本。

- 修复 qwen3.7-plus HTTP 200 被误判为 `FAILED_JSON_CAPABILITY`。
- 增加 JSON 围栏和嵌入 JSON 兼容。
- 分离视觉能力与 JSON 能力，并单独报告严格 JSON 能力。
- 默认关闭 qwen3.7 思考，使用阿里云兼容的 `json_object` 输出格式。
- 真实 DashScope 按量 API 验证通过：marker 为 `VISION-7319`，三项能力均为 true。
- Key 未进入 Git，公共 API 无法回读 Key。

本版本不包含 OCR 性能、多核、Mac 适配或 Pipeline 重构；这些工作进入 v1.0.2。

## 发布勘误

- 不可变的 `v1.0.1` Tag 中，`docs/RELEASE_CHECKLIST.md` 保留了发布时的未勾选状态，并误写为 PR #1；正确的追溯清单已在发布后的 `master` 中更正为 PR #2。该文档错误不影响 Tag 中的运行代码、测试 Gate 或 Secret 安全。
- `SHA256SUMS.txt` 只包含源码 ZIP 的正式校验值；GitHub 为四项 Release 资产公开提供各自的 digest，但仓库校验清单未覆盖两个文本资产。
- 源码 ZIP 包含允许的非敏感回归清单 `tests/fixtures/private/golden_cases.yaml` 和目录占位文件；不包含真实私密图片、API Key、用户配置或原始 API 响应。
