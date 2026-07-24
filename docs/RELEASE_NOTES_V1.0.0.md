# daily-record-ocr-lite v1.0.0

首个稳定版提供 PP-OCRv6 + OpenAI-compatible 视觉模型双引擎、页面布局证据、严格
数字冲突、公司—产品—配方分组、局部 OCR/VLM 复核、唯一 FinalResult 与五 Sheet
Excel 导出。

新增 `/setup`、`/settings`、安全配置 CLI、doctor、Windows/Linux/macOS 安装入口、
AI 安装协议、跨任务缓存和完整 CI/Release Gate。

用户必须配置自己的视觉模型。未配置时应用为 `SETUP_REQUIRED`；Mock 只能显式进入
Demo，导出带 `DEMO-` 前缀，绝不会伪装成对上传图片的真实识别。

支持 Python 3.11/3.12；Windows/Linux CPU 是主要安装路径，NVIDIA 与 macOS 必须按
PaddlePaddle 当前官方兼容矩阵选择 wheel。完整矩阵见
`docs/SUPPORTED_ENVIRONMENTS.md`。

识别图片、缓存、FinalResult、Excel 和 API Key 默认只保存在本机 `data/`；只有用户
配置的视觉模型请求会把图像发送到对应 Provider。提交 issue 前请按
`docs/DATA_AND_PRIVACY.md` 脱敏。

升级前备份 `data/` 并保持工作区干净。Windows 使用
`install/update-windows.ps1 -Ref master`；其他平台按
`docs/AI_AGENT_UPGRADE.md` 执行等价的备份、快进更新、依赖更新与完整验收。

已知限制：手写质量、复杂表格和视觉模型能力会影响准确率；NVIDIA/macOS 的 Paddle
安装依赖当前官方兼容矩阵；CPU 为兼容 Paddle 3.3.x 默认关闭 MKL-DNN，速度可能
低于启用加速的环境；v1 不提供未确认冲突的强制导出。
