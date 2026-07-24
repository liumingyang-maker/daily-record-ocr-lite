# 支持环境

应用支持 Python 3.11/3.12。CI 覆盖 Ubuntu 的 3.11/3.12 与 Windows 安装烟雾。
Windows/Linux CPU 是主要路径；NVIDIA 依赖 Paddle 当前 CUDA 兼容矩阵。macOS
Apple Silicon/Intel 是否能运行 Paddle 取决于当前官方 wheel，应在安装时确认。
CPU 路径为规避 Paddle 3.3.x oneDNN/PIR 已知推理故障，默认关闭 MKL-DNN；这会牺牲
部分性能，但不降低 PP-OCRv6 模型档位或替换真实结果。

核心 Web 层可在无 OCR 时启动 `/setup`，但状态只能是 `SETUP_REQUIRED` 或显式
`DEMO_MODE`，不能视为真实识别支持。
