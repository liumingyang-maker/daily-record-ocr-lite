# AI Agent 安装指南

先读取根目录 `AGENTS.md`。支持矩阵分为 Windows CPU、Windows NVIDIA、macOS
Apple Silicon、macOS Intel、Linux CPU、Linux NVIDIA 和其他设备。Python 必须为
3.11 或 3.12。

安装前必须查阅 [PaddlePaddle 当前安装文档](https://www.paddlepaddle.org.cn/install/quick)
与 [PaddleOCR 当前安装文档](https://www.paddleocr.ai/latest/en/version3.x/installation.html)。
NVIDIA 安装命令取决于驱动、CUDA、平台和当前 wheel，不能从旧文档或记忆猜测。

## 执行路径

- Windows CPU：`.\install\install-windows.ps1 -OcrMode Cpu`
- Windows NVIDIA：将官方命令传给
  `.\install\install-windows.ps1 -OcrMode Gpu -PaddleInstallCommand "…"`
- Linux CPU：`./install/install-linux.sh`
- Linux NVIDIA：`./install/install-linux.sh --paddle-install-command "…"`
- macOS Apple Silicon / Intel：先确认当前官方支持，再传
  `./install/install-macos.sh --paddle-install-command "…"`
- 其他设备：若无官方 wheel，报告不支持原因；可 `--skip-ocr` 进入
  `SETUP_REQUIRED`，不得声称真实识别已安装。

脚本完成后依次运行真实 OCR、配置视觉模型、连接测试和 `doctor --full`。最终输出
AGENTS.md 规定的 `INSTALL_REPORT`。任何全 skip 的 real_ocr 运行都视为失败。

## AI 执行清单

1. 记录操作系统、架构、Python 版本、CPU/GPU、驱动/CUDA（如有），确认项目在
   `master` 或目标稳定 tag。
2. 运行对应安装入口；GPU 参数只能来自本次查询到的官方兼容矩阵。
3. 在项目 `.venv` 中安装 `requirements-dev.txt`，然后运行：

   ```text
   python -m pytest -m "not real_ocr" -q
   python -m ruff check lite_app tests_lite scripts
   python -m pytest -m real_ocr -q -s
   ```

4. `real_ocr` 必须报告至少一个 passed，并确认输出 provider 为
   `paddleocr_v6`、模型为选择的 `PP-OCRv6_<tier>`；skip 或零 token 都不能通过。
5. 使用 `/setup` 或 `docs/AI_AGENT_CONFIGURE.md` 配置用户自己的 Provider、模型与
   Key，分别执行 OCR 与 Vision 测试，再用一张用户授权的真实图片验收。
6. 运行 `python scripts/doctor.py --full --json`。退出码 0 才是 READY；退出码 1
   必须在报告中列出尚待用户配置的项目；退出码 2 必须停止并修复。

不要在命令行参数、日志、截图或 `INSTALL_REPORT` 中放 API Key。失败报告应包含脱敏
命令、退出码、最后一段错误、已尝试修复以及需要用户完成的动作；不得用 Demo/Mock
替代失败的真实 OCR 或 Vision Gate。
