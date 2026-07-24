# macOS 安装

Apple Silicon 与 Intel 的 Paddle wheel 支持会变化，安装前必须查询当前官方文档。
准备 Python 3.11/3.12 后：

```text
./install/install-macos.sh --paddle-install-command "官方给出的当前命令"
./start-macos.command
```

若当前架构没有官方 Paddle 支持，应明确报告限制；`--skip-ocr` 只允许开发/Demo，
不能通过真实 OCR Gate。
