# AI 安装与维护协议

## 项目

本项目把手写生产/配方记录经 PP-OCRv6 与视觉模型双引擎识别、复核后导出
Excel。稳定分支是 `master`，稳定版本是 `v1.0.1`，支持 Python 3.11/3.12。

## 强制规则

1. 不要只执行 `pip install -r requirements.txt` 就声称安装完成。
2. Mock 只能由用户显式进入 Demo；不得把固定结果描述成对上传图片的真实识别。
3. 根据操作系统、CPU/GPU、驱动与 CUDA，查阅 PaddlePaddle 和 PaddleOCR 当前官方安装文档；不要猜 GPU wheel。
4. 不要读取、打印或提交 API Key。使用 `scripts/configure.py set-key`。
5. `doctor` 为 `BROKEN` 时不得启动生产识别、合并或发布。
6. 不得删除 `data/`；卸载时只有用户显式 `-PurgeData` 才能删除。

## 安装流程

1. 检测 Windows/macOS/Linux、架构、Python、GPU/驱动。
2. 使用 `install/` 对应入口安装核心依赖。
3. 按当前官方矩阵安装 PaddlePaddle，再安装 PaddleOCR/OpenCV。
4. 运行 `python scripts/doctor.py --json`。
5. 运行 `python -m pytest -m real_ocr -q -s`，必须至少有真实推理通过，不能全 skip。
6. 用 `/setup` 或 `scripts/configure.py` 配置用户自己的视觉模型。
7. 运行 `python scripts/configure.py test-vision` 和实际图片验收。
8. 运行 `python scripts/doctor.py --full --json`。

配置命令见 `docs/AI_AGENT_CONFIGURE.md`；升级见 `docs/AI_AGENT_UPGRADE.md`。
执行下面的源码验收前，先在项目 `.venv` 中安装 `requirements-dev.txt`；这一步只为
测试/静态检查，不替代 OCR 依赖安装。

## 验收

```text
python -m pytest -m "not real_ocr" -q
python -m ruff check lite_app tests_lite scripts
python -m pytest -m real_ocr -q -s
python scripts/doctor.py --full --json
```

## INSTALL_REPORT

最终报告必须列出：系统/架构、Python、安装入口、Paddle/PaddleOCR/OpenCV 版本、
OCR provider/tier/device、真实 OCR 测试通过数、Vision 配置/连接状态、doctor 状态、
应用 URL、Demo 是否关闭、未完成项及下一步。失败时同时提供失败命令、退出码、
最后一段错误（脱敏）、已尝试修复和用户需要采取的动作。
