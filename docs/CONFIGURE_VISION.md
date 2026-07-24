# 配置视觉模型

支持 OpenAI Chat Completions 兼容的视觉模型端点。需要 provider、base URL、endpoint、
model 和 API Key。可在 `/settings` 配置，或使用 `scripts/configure.py`。

保存后先运行连接测试。HTTP 401 通常是 Key/权限问题；连接拒绝通常是 base URL 或
服务状态；返回非 JSON 说明模型/代理未遵循要求。原始响应保存在任务
`vision/raw_response.txt`，但日志和设置 API 不保存/返回 API Key。
