# 平台安装入口

- Windows：`.\install\install-windows.ps1 -OcrMode Cpu`
- Linux：`./install/install-linux.sh`
- macOS：先查阅 PaddlePaddle/PaddleOCR 当前官方兼容矩阵，再使用
  `./install/install-macos.sh --paddle-install-command "…"`

`SkipOcr`/`--skip-ocr` 只面向开发或显式演示。脚本结束时 `doctor` 可以返回
`SETUP_REQUIRED`（等待视觉模型配置），但不能返回 `BROKEN`。

Windows 安装/更新流程使用临时短盘符解包 Paddle 的深层 wheel 路径，并在结束时清理；
虚拟环境仍位于项目的 `.venv`。

GPU 的 Paddle 安装命令必须按当前驱动、CUDA 和平台从官方文档选择，脚本不猜测。
