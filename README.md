# daily-record-ocr（轻量版）

将手机拍摄的中文手写生产/配方笔记识别为结构化数据，允许人工校对，并写入 Excel。

## 为什么不用固定坐标切格

用户的手写笔记是自由排版的活页本，不是固定印刷表格。手机拍摄方向可能与文字方向相差 90°，页面可能有阴影、倾斜和金属活页环。固定坐标切格无法适应这些变化。

本项目使用**整图视觉理解**：将完整图片交给可配置的视觉模型，由模型理解空间关系后返回结构化 JSON。

## 架构

```
上传图片 → EXIF/旋转/缩放预处理 → 视觉模型 Provider → JSON 解析
    → JSON Schema 校验 → 浏览器人工校对 → Excel 导出 → 下载
```

核心模块：

- `lite_app/config.py` — 集中配置（YAML + .env + 环境变量占位）
- `lite_app/storage.py` — 文件夹 + JSON 任务存储
- `lite_app/image_utils.py` — 图片预处理（EXIF、旋转、缩放、JPEG）
- `lite_app/providers.py` — VisionProvider 抽象 + mock / openai_compatible
- `lite_app/pipeline.py` — 提示词构建、模型调用、JSON 提取、Schema 校验
- `lite_app/exporter.py` — Excel 新建 / 固定模板映射导出
- `lite_app/main.py` — FastAPI 页面与 API

## 安装要求

- Python 3.11+
- 无需 Node.js、Docker、数据库

## 安装和启动

### Windows

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python -m app.main
```

### macOS / Linux

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m app.main
```

启动后访问 http://127.0.0.1:8765

也可使用 uvicorn 直接启动：

```bash
uvicorn lite_app.main:app --host 127.0.0.1 --port 8765
```

## 默认 Mock 模式

未配置任何 API Key 时，默认使用 mock provider。它会读取 `config/mock_result.json` 返回预设结果，可以在没有模型的情况下完整体验上传、校对、导出流程。

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

## 自定义 Provider

在 `lite_app/providers.py` 中继承 `VisionProvider`：

```python
class MyVisionProvider(VisionProvider):
    async def analyze(self, image_paths, system_prompt, user_prompt, json_schema) -> str:
        # 调用自定义服务
        return '{"page_heading":"","records":[],"warnings":[]}'
```

然后在 `build_provider()` 中注册名称即可。无需修改识别流程、页面和导出器。

## 修改识别 Schema

编辑 `config/record_schema.yaml`：

- `system_prompt` — 系统提示词
- `instructions` — 用户提示词中的识别规则
- `schema` — JSON Schema（Draft 2020-12），用于校验模型输出

## 固定 Excel 模板配置

编辑 `config/export.yaml`：

1. 将你的模板文件放到 `config/` 或其他本地路径
2. 设置 `template_path: config/my_template.xlsx`
3. 根据真实 Sheet 名、起始行和列字母调整 `cells` 和 `tables` 映射
4. 合并单元格只能写左上角主单元格
5. 模板不会被修改，输出另存到任务目录
6. 若模板是 `.xlsm` 且需保留宏，设置 `keep_vba: true`

不设置 `template_path` 时，自动创建包含"记录汇总"、"配方明细"、"工艺参数"三个 Sheet 的新工作簿。

## 任务文件保存位置

所有任务数据保存在 `data/jobs/` 下，每个任务一个独立目录：

```
data/jobs/20260723-221530-a1b2c3/
├── job.json          # 任务元数据
├── source_01_*.jpg   # 原始上传
├── prepared_01.jpg   # 处理后图片
├── raw_response.txt  # 模型原始响应
├── result.json       # 识别结果
└── recognized-*.xlsx # 导出文件
```

## 常见错误排查

| 错误 | 原因和解决 |
|------|-----------|
| 视觉模型接口超时 | 检查模型服务是否运行，或增大 `timeout_seconds` |
| HTTP 401 | API Key 错误，检查 `.env` 中 `VISION_API_KEY` |
| 无法连接视觉模型服务 | 检查 `VISION_BASE_URL` 地址是否正确 |
| 文件不是可识别的图片 | 上传的文件不是有效图片格式 |
| Excel 模板不存在 | 检查 `export.yaml` 中 `template_path` 路径 |
| Schema 校验不通过 | 在详情页查看具体错误，手动修正 JSON |

## 测试

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

测试不调用外网，使用 mock provider 和 httpx.MockTransport。

## Legacy 实现说明

本项目是轻量重写版，不依赖 PaddleOCR、OpenCV、SQLAlchemy 等重型组件。若仓库中存在旧实现代码，其依赖在 `requirements-legacy.txt` 中，默认安装不会安装这些包。

## 数据隐私

- 图片默认保存在本机 `data/jobs/` 目录
- 只有使用远程模型时，处理后的图片才会发送给所配置的视觉模型服务
- 使用本地模型（如 Ollama）时，数据不出本机
- 不收集任何遥测数据
