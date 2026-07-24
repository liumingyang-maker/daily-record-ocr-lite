# daily-record-ocr-lite（准确率优先增强版）

将手机拍摄的中文手写生产/配方笔记识别为结构化数据，允许人工校对，并写入 Excel。

[![CI](https://github.com/liumingyang-maker/daily-record-ocr-lite/actions/workflows/ci.yml/badge.svg?branch=feature/accuracy-first-dual-engine)](https://github.com/liumingyang-maker/daily-record-ocr-lite/actions/workflows/ci.yml)

## 核心设计：双引擎识别 + 空间关联融合

本项目使用 **PP-OCRv6 + 视觉大模型** 双引擎互相验证：

- PP-OCRv6 提供文字、坐标和置信度
- 视觉大模型接收原图 + OCR 证据（含坐标），理解空间关系
- **空间关联融合**：通过 evidence_token_ids → bbox IoU → 中心距离三策略关联 OCR 与 VLM 候选
- **严格数字冲突检测**：OCR≠VLM 时强制 CONFLICT，历史候选不能覆盖
- **识别缓存**：OCR 和 VLM 阶段均检查缓存，相同图片+模型+prompt 版本不重复调用
- **Draft202012 Schema 校验**：VLM 输出在 pipeline 中实时校验
- 历史物料/配方匹配辅助纠错
- 冲突字段局部裁图复核
- 字段级人工确认（Confirm All 检查未解决冲突）
- 失败标记 DEGRADED，不静默回退

## 架构

```
上传图片 → VLM/OCR 双图预处理 → [缓存检查]
    → PP-OCRv6 整图识别 → [写入OCR缓存]
    → 视觉大模型（带 OCR 证据）→ [Schema校验] → [写入VLM缓存]
    → 历史匹配 → 空间关联融合 → 冲突检测
    → 局部复核 → 字段级人工确认
    → 公司—产品—配方分组 → Excel 5-Sheet 导出
```

核心模块：

- `lite_app/ocr/` — OCRProvider 抽象 + PaddleOCRv6（tier→模型名映射）+ Mock + 单例 + Overlay
- `lite_app/vision/` — VisionProvider 抽象 + mock / openai_compatible
- `lite_app/layout/` — 行聚类、原料-数量横向配对、记录分组
- `lite_app/knowledge/` — sqlite3 知识库 + 历史匹配器 + 公司/产品别名
- `lite_app/fusion/` — 候选融合引擎 + 严格数字冲突检测
- `lite_app/grouping/` — 公司—产品—配方业务分组 + 三视图 + 分组Excel导出
- `lite_app/review/` — 局部复核 + 修正日志
- `lite_app/cache.py` — 识别缓存（图片哈希+模型+prompt版本）
- `lite_app/pipeline_v2.py` — 双引擎集成 pipeline（含缓存+Schema校验+空间关联）
- `lite_app/image_utils_v2.py` — VLM/OCR 双图预处理（可选 OpenCV CLAHE）
- `lite_app/exporter.py` — Excel 5-Sheet 导出
- `lite_app/main.py` — FastAPI 页面与 API（37 路由）

## 安装要求

- Python 3.11+
- 无需 Node.js、Docker、数据库
- 推荐安装 OCR 依赖以获得最佳准确率

## 安装和启动

### Windows

```powershell
python -m venv venv
venv\Scripts\activate
# 推荐：安装含 OCR 的完整依赖
pip install -r requirements-ocr.txt
# 或仅核心依赖（无 OCR，降级运行）
# pip install -r requirements.txt
python -m app.main
```

### macOS / Linux

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-ocr.txt
python -m app.main
```

启动后访问 http://127.0.0.1:8765

验证安装：

```bash
python scripts/verify_install.py
```

也可使用 uvicorn 直接启动：

```bash
uvicorn lite_app.main:app --host 127.0.0.1 --port 8765
```

## PP-OCRv6 模型配置

`config/recognition.yaml` 中 `ocr.tier` 映射真实模型名：

| tier | 检测模型 | 识别模型 |
|------|---------|---------|
| tiny | PP-OCRv6_mobile_det | PP-OCRv6_mobile_rec |
| small | PP-OCRv6_mobile_det | PP-OCRv6_server_rec |
| medium | PP-OCRv6_server_det | PP-OCRv6_server_rec |

## 默认 Mock 模式

未配置任何 API Key 时，默认使用 mock provider。读取 `config/mock_result.json`（pages[] 格式）返回预设结果，包含公司/产品/多配方结构，可完整体验分组和导出流程。

## 接入 OpenAI-compatible 视觉模型

复制 `.env.example` 为 `.env`，修改以下字段：

```env
VISION_PROVIDER=openai_compatible
VISION_BASE_URL=http://127.0.0.1:11434/v1
VISION_ENDPOINT=/chat/completions
VISION_API_KEY=your-api-key
VISION_MODEL=qwen-vl
```

支持任何兼容 OpenAI Chat Completions 接口的视觉模型服务（Ollama、vLLM、OpenAI、Azure 等）。

## 识别结果页面

上传后默认跳转到 `/jobs/{id}/result`（分组结果页），提供三种视图：

- **按公司**：公司 → 产品/系列 → 配方（默认）
- **按图片**：图片 → 页面公司 → 配方
- **仅看待确认**：只显示有冲突或待复核的配方

点击配方查看材料/工艺表，点击字段查看 OCR/VLM/历史候选证据。

## 任务文件保存位置

```
data/jobs/20260723-221530-a1b2c3/
├── job.json                    # 任务元数据（含 cache_hits、timings_ms）
├── source_01_*.jpg             # 原始上传
├── prepared_vlm_01.jpg         # VLM 预处理图
├── prepared_ocr_01.jpg         # OCR 预处理图（灰度+CLAHE）
├── ocr/
│   ├── page_01_base.json       # OCR 结果（含坐标）
│   └── page_01_overlay.jpg     # OCR 检测框可视化
├── vision/
│   ├── raw_response.txt        # VLM 原始响应
│   └── structured_result.json  # VLM 结构化结果
├── fusion/
│   └── result.json             # 融合结果（final_value 为唯一导出源）
├── review/
│   └── business_entities.json  # 公司—产品—配方分组
└── recognized-*.xlsx           # 导出文件
```

## 常见错误排查

| 错误 | 原因和解决 |
|------|-----------|
| DEGRADED 状态 | 双引擎识别失败，检查 OCR/VLM 配置后重新识别 |
| 视觉模型接口超时 | 检查模型服务是否运行，或增大 `timeout_seconds` |
| HTTP 401 | API Key 错误，检查 `.env` 中 `VISION_API_KEY` |
| 无法连接视觉模型服务 | 检查 `VISION_BASE_URL` 地址是否正确 |
| 文件不是可识别的图片 | 上传的文件不是有效图片格式 |
| Confirm 返回 REVIEW_REQUIRED | 存在未解决冲突或关键空字段，需先处理 |
| Schema 校验不通过 | 在详情页查看具体错误，手动修正 JSON |

## 测试

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

- 164 个测试通过，5 个 real_ocr 跳过（需安装 paddleocr）
- CI: Python 3.11 + 3.12 全绿
- 测试不调用外网，使用 mock provider 和 httpx.MockTransport

运行真实 OCR 测试：

```bash
pip install -r requirements-ocr.txt
python -m pytest -m real_ocr -v
```

## 数据隐私

- 图片默认保存在本机 `data/jobs/` 目录
- 只有使用远程模型时，处理后的图片才会发送给所配置的视觉模型服务
- 使用本地模型（如 Ollama）时，数据不出本机
- 不收集任何遥测数据
- API Key 不在日志/页面/响应中输出
