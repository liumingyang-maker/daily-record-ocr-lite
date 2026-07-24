# Changelog

## 1.0.1

- 修复 qwen3.7-plus 返回 HTTP 200 时被误判为 `FAILED_JSON_CAPABILITY`。
- 增加 Markdown JSON 围栏和说明文字内嵌 JSON 对象兼容。
- 分离视觉能力、JSON 响应能力和严格 JSON 能力。
- 阿里云兼容端点上的 qwen3.7-plus 默认关闭思考并使用 `json_object`。
- 增加脱敏响应预览；不包含 OCR 性能、Mac 适配或 Pipeline 重构。

## 1.0.0

- 建立严格 `record-v1`、`recheck-v1`、`settings-v1` 数据契约。
- 接入 PP-OCRv6 官方 tiny/small/medium 模型映射、分页 token ID、布局和多 token 关联。
- 以 `review/final_result.json` 作为人工修改、分组投影和 Excel 的唯一正式数据源。
- 完成局部 OCR/VLM 批量复核、跨任务缓存、fail-closed 状态与原子持久化。
- 增加 Setup/Settings、显式 Demo、安全 CLI、doctor 和跨平台安装产品层。
- 增加 Python 3.11/3.12、Windows smoke、真实 OCR 与 Release 工作流。
