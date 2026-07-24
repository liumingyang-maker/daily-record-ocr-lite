# 故障排查

- `SETUP_REQUIRED`：安装本身可用，但真实 OCR 依赖或视觉模型未就绪。
- `BROKEN`：查看 `doctor --json` 中 critical FAIL，修复后再启动。
- `FAILED_SCHEMA`：模型输出不符合 record-v1；原始响应仍保留，任务不能 READY。
- `REVIEW_REQUIRED`：存在冲突、待确认或关键空字段，确认前不能正式导出。
- Paddle 加载失败：核对 Python/平台/CPU-GPU/驱动与官方 wheel，不要静默切 Mock。
- Paddle 3.3.x CPU 若报 `ConvertPirAttribute2RuntimeAttribute`，这是 oneDNN/PIR
  推理路径的已知上游问题（PaddleX #4970）。本项目 CPU Provider 已显式关闭
  MKL-DNN 以保证正确性；不要删除该兼容设置后声称 real_ocr 通过。
- 端口占用：设置 `APP_PORT` 或结束占用进程。
- Key：用 `configure.py set-key` 重新写入；不要把 Key 粘贴到 issue/日志。

报告问题时附 doctor 脱敏 JSON、平台、Python、失败命令和任务状态；不要附私有图片或
`data/secrets.env`。
