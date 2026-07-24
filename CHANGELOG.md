# Changelog

## 1.0.0

- 建立严格 `record-v1`、`recheck-v1`、`settings-v1` 数据契约。
- 接入 PP-OCRv6 官方 tiny/small/medium 模型映射、分页 token ID、布局和多 token 关联。
- 以 `review/final_result.json` 作为人工修改、分组投影和 Excel 的唯一正式数据源。
- 完成局部 OCR/VLM 批量复核、跨任务缓存、fail-closed 状态与原子持久化。
- 增加 Setup/Settings、显式 Demo、安全 CLI、doctor 和跨平台安装产品层。
- 增加 Python 3.11/3.12、Windows smoke、真实 OCR 与 Release 工作流。
