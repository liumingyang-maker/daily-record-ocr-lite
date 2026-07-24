# AI Agent 配置指南

Web 与 CLI 共用 `SettingsService`。非秘密写入 `data/settings.json`，API Key 写入
`data/secrets.env`；公开 API 只返回 `api_key_configured`，绝不回显明文。

```text
python scripts/configure.py status --json
python scripts/configure.py vision --provider openai_compatible --base-url URL --endpoint /chat/completions --model MODEL
python scripts/configure.py set-key
python scripts/configure.py ocr --provider paddleocr_v6 --tier medium --device cpu
python scripts/configure.py test-ocr --image PATH
python scripts/configure.py test-vision
```

无人值守时先把 Key 放进进程环境，再运行
`python scripts/configure.py set-key --from-env VISION_API_KEY`。命令行参数中不要放
Key。配置后运行 `doctor --full --json` 和一张用户授权的真实图片。Demo 只能由
用户在 `/setup` 明确确认，正式验收前必须关闭。
