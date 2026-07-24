# daily-record-ocr-lite

[![CI](https://github.com/liumingyang-maker/daily-record-ocr-lite/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/liumingyang-maker/daily-record-ocr-lite/actions/workflows/ci.yml)
[![Real OCR](https://github.com/liumingyang-maker/daily-record-ocr-lite/actions/workflows/real-ocr.yml/badge.svg?branch=master)](https://github.com/liumingyang-maker/daily-record-ocr-lite/actions/workflows/real-ocr.yml)

当前稳定版本：`v1.0.1`

把中文手写生产/配方记录经 PP-OCRv6 与视觉模型双引擎识别、人工复核，并导出为
公司—产品—配方结构的 Excel。

## 让 AI 安装

把仓库链接和下面这段话发给你的安装 AI：

> 请克隆此仓库，读取根目录 AGENTS.md 和 docs/AI_AGENT_INSTALL.md，根据我的操作
> 系统完成安装、PP-OCRv6 真实验证、视觉模型配置和 doctor 验收。禁止使用 Mock
> 结果冒充真实识别。

AI 必须输出 `INSTALL_REPORT`，包括真实 OCR 通过数与 doctor 状态。

## 真实模式与 Demo

全新安装默认是 `SETUP_REQUIRED`：没有配置视觉模型时不接受识别任务。Mock 只能由
用户在 `/setup` 显式开启；所有页面显示警示，导出名以 `DEMO-` 开头，结果与上传
图片无关。

## 最快安装

Python 支持 3.11/3.12。

Windows CPU：

```powershell
.\install\install-windows.ps1 -OcrMode Cpu
.\start-windows.bat
```

Linux CPU：

```text
./install/install-linux.sh
./start-linux.sh
```

GPU 与 macOS 安装前必须查询 PaddlePaddle/PaddleOCR 当前官方兼容矩阵。详细入口见
[`install/README.md`](install/README.md) 和 `docs/INSTALL_*.md`。

## 首次配置

启动后访问 <http://127.0.0.1:8765/setup>，或使用：

```text
python scripts/configure.py vision --provider openai_compatible --base-url URL --endpoint /chat/completions --model MODEL
python scripts/configure.py set-key
python scripts/configure.py ocr --provider paddleocr_v6 --tier medium --device cpu
python scripts/configure.py test-ocr --image PATH
python scripts/configure.py test-vision
python scripts/doctor.py --full --json
```

API Key 只写入环境或 `data/secrets.env`，不会由设置 API 回显。

## 识别与数据流

```text
上传 → OCR/Vision 双图预处理
     → PP-OCRv6（文本、坐标、置信度）
     → 行/配对/记录布局证据
     → 视觉模型（原图 + OCR/Layout）
     → record-v1 严格校验
     → evidence token / bbox / center 多 token 关联与融合
     → review/final_result.json
     → 人工修改或一次局部 OCR/VLM 复核
     → BusinessEntities 投影 → 五 Sheet Excel
```

数字 OCR 与视觉模型不一致时强制 `CONFLICT`。Schema 错误、缺失 FinalResult、关键
空字段或未确认项都不能进入 READY/正式导出。人工字段修改同步 FinalResult、融合、
修正日志、业务投影和 Excel；原始视觉结果保留在 `vision/structured_result.json`。

## 验证

```text
python -m pytest -m "not real_ocr" -q
python -m ruff check lite_app tests_lite scripts
python -m pytest -m real_ocr -q -s
python scripts/doctor.py --json
python scripts/verify_release.py
```

真实 OCR Gate 必须实际加载 PP-OCRv6 并完成推理，不能全 skip。

## 任务目录

```text
data/jobs/<job-id>/
├── source/                  # 原始上传
├── preprocess/              # OCR/Vision 双图
├── ocr/                    # 原始 OCR 与 overlay
├── layout/                 # lines / pairs / records
├── vision/                 # raw_response / structured_result / schema_errors
├── fusion/                 # candidates / result
├── review/
│   ├── final_result.json   # 唯一正式结果
│   ├── business_entities.json
│   ├── recheck_result.json
│   ├── corrections.json
│   └── job_events.json
└── export/recognized-*.xlsx
```

跨任务缓存位于 `data/cache/{ocr,vision}`。隐私和删除规则见
[`docs/DATA_AND_PRIVACY.md`](docs/DATA_AND_PRIVACY.md)。

## 文档

- 视觉配置：[`docs/CONFIGURE_VISION.md`](docs/CONFIGURE_VISION.md)
- 故障排查：[`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md)
- 支持环境：[`docs/SUPPORTED_ENVIRONMENTS.md`](docs/SUPPORTED_ENVIRONMENTS.md)
- AI 升级：[`docs/AI_AGENT_UPGRADE.md`](docs/AI_AGENT_UPGRADE.md)
- v1.0.1 说明：[`docs/RELEASE_NOTES_V1.0.1.md`](docs/RELEASE_NOTES_V1.0.1.md)

## 已知限制

手写质量、复杂表格和所选视觉模型会影响准确率；NVIDIA/macOS 的 Paddle 安装依赖
当前官方 wheel；v1 不支持绕过未确认项强制正式导出。本地应用默认只监听
`127.0.0.1`，不应直接暴露公网。
