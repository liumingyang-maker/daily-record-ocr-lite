# AI Agent 升级指南

升级前确认工作区干净，记录当前 tag/commit，并备份 `data/`。Windows 使用：

```powershell
.\install\update-windows.ps1 -Ref master
```

Windows 更新器会复用加固后的安装器。GPU 用户应继续传入
`-OcrMode Gpu -PaddleInstallCommand "官方安装命令"`；显式 Demo/开发环境才可使用
`-SkipOcr`。

其他平台执行同等步骤：备份数据、`git fetch --tags`、切换目标稳定 tag/master、
`git pull --ff-only`、更新核心与 OCR 依赖、运行全部非真实测试、真实 OCR 和
`doctor --full`。不要 reset/clean 用户修改。失败时保留备份和旧 `.venv`，输出
失败命令与恢复路径。
