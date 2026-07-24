# Windows 安装

安装 64 位 Python 3.11/3.12 和 Git。CPU：

```powershell
git clone https://github.com/liumingyang-maker/daily-record-ocr-lite.git
cd daily-record-ocr-lite
.\install\install-windows.ps1 -OcrMode Cpu
.\start-windows.bat
```

安装器会临时映射一个空闲短盘符，避免 Paddle wheel 的深层文件在较长项目路径下触发
Win32 路径限制；无论成功或失败都会清理该映射，`.venv` 仍保存在项目目录。

NVIDIA 环境先按当前 PaddlePaddle 官方矩阵确认驱动/CUDA，再用
`-PaddleInstallCommand`。首次访问 `/setup` 配置自己的视觉模型。`doctor` 的
`SETUP_REQUIRED` 表示仍待配置；`BROKEN` 必须先修复。
