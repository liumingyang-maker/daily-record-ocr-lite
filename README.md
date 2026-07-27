# daily-record-ocr-lite

[![CI](https://github.com/liumingyang-maker/daily-record-ocr-lite/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/liumingyang-maker/daily-record-ocr-lite/actions/workflows/ci.yml)
[![Real OCR](https://github.com/liumingyang-maker/daily-record-ocr-lite/actions/workflows/real-ocr.yml/badge.svg?branch=master)](https://github.com/liumingyang-maker/daily-record-ocr-lite/actions/workflows/real-ocr.yml)

## 让其他 AI 整理历史配方

请让 AI 生成带 Manifest、JSONL、必要证据和 SHA-256 的标准 ZIP，不要让 AI
直接修改 SQLite。系统先预检和预览，用户明确确认后才事务导入。可复制提示词、
精确字段、排除规则、ZIP 目录和校验命令见
[`docs/AI_KNOWLEDGE_PACKAGE.md`](docs/AI_KNOWLEDGE_PACKAGE.md)。

将中文手写生产记录、配方记录或日常记录图片，通过 PP-OCRv6、Qwen3.7 Plus 视觉模型、
OCR/Layout/Vision 融合和人工复核，转换为结构化记录，并导出为 Excel。

**主要流程：**

上传图片 → OCR → Vision → 配方卡片确认 → 追加到知识库 → READY → Excel 导出

> **注意：** 人工复核是正式导出的安全步骤，不是可选功能。

## 当前版本状态

- **当前稳定 Release：** [`v1.0.1`](https://github.com/liumingyang-maker/daily-record-ocr-lite/releases/tag/v1.0.1)
- **下一版本 Draft：**
  - [PR #7](https://github.com/liumingyang-maker/daily-record-ocr-lite/pull/7)：证据优先的配方卡片审查与按日期追加的知识历史
  - [PR #8](https://github.com/liumingyang-maker/daily-record-ocr-lite/pull/8)：Windows x64 EXE 与 Apple Silicon macOS DMG 安装层
  - PR #8 的 Windows/macOS 未签名原生测试 Gate 已通过；正式签名、公证、合并和 Release 尚未执行

**普通用户只使用最新稳定 Release；开发或抢先体验用户才使用 Draft 分支或 master。**

## 选择安装方式

普通用户优先从 [最新稳定 Release](https://github.com/liumingyang-maker/daily-record-ocr-lite/releases/latest)
下载正式资产。如果当前 Release 没有 Windows EXE 或 macOS DMG，请使用下方 Git 安装方式，
不要把文件名带 `UNSIGNED` 的 CI Artifact 当作正式安装包。

桌面安装层将应用文件与用户数据分开。Windows 数据位于 `%LOCALAPPDATA%\DailyRecordOCR`，
macOS 数据位于 `~/Library/Application Support/DailyRecordOCR`；安装新版不会用程序文件覆盖
settings、secrets、jobs、知识库或导出的 Excel。

## Windows 快速开始

### 1. 安装前置条件

- 安装 [Git](https://git-scm.com/)
- 安装 Python 3.11 或 3.12

### 2. 克隆并安装

```powershell
git clone https://github.com/liumingyang-maker/daily-record-ocr-lite.git
cd daily-record-ocr-lite
.\install\install-windows.ps1 -OcrMode Cpu
```

### 3. 首次安装的正常结果

安装完成后，你会看到：

```
Doctor state: SETUP_REQUIRED
Doctor exit code: 1
Installer exit code: 0
```

**这不是安装失败！** 只是尚未配置视觉模型。

### 4. 启动程序

```powershell
.\start-windows.bat
```

### 5. 访问配置页面

浏览器打开：http://127.0.0.1:8765/setup

## Vision 配置

在 `/setup` 页面或使用命令行配置：

| 配置项 | 值 |
|--------|-----|
| Provider | `openai_compatible` |
| Base URL | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| Endpoint | `/chat/completions` |
| Model | `qwen3.7-plus` |
| API Key | 你的 `sk-ws` 按量 API Key |

**重要说明：**

- 不使用 Token Plan 作为自定义应用后端
- 不把 API Key 提交到 Git
- Key 保存在本机配置或 `data/secrets.env`
- 请求超时至少 300 秒
- 单次真实识别可能耗时约 90 至 120 秒
- 页面等待期间不要重复提交同一个任务

## OCR 配置

默认真实 OCR：

| 配置项 | 值 |
|--------|-----|
| Provider | `paddleocr_v6` |
| Tier | `medium` |
| Device | `cpu` |

Windows CPU 普通用户使用默认安装命令即可。

**说明：** 第一次加载 PP-OCRv6 可能较慢，后续会使用本地模型和缓存。

## 首次使用流程

### 第一次识别

1. 打开应用（`.\start-windows.bat`）
2. 浏览器访问 http://127.0.0.1:8765
3. 上传一张或多张手写记录图片；可在上传前调整顺序并分别旋转
4. 等待 OCR 和 Vision 完成（约 90-120 秒）
5. 查看状态：
   - 若状态为 `REVIEW_REQUIRED`，进入人工复核
   - `REVIEW_REQUIRED` 是正常安全状态，不是失败
6. 页面会先展开冲突、空值和低可信配方；对照原图修改客户、产品、日期、材料、数量和工艺
7. 点击每张卡片的“确认这条配方”；日期、客户、产品、材料名称和数量缺失时不能确认
8. 所有卡片确认后，点击“确认完成并加入知识库”
9. 系统按“客户 + 产品 + 日期”追加历史记录，不会覆盖以前的配方
10. 状态变为 `READY` 后导出 Excel

**只有正式结果、配方确认和知识库回执完全匹配时才会进入 `READY`，然后才能正式导出 Excel。**

## 配方知识库

知识库默认按“客户 → 产品 → 日期”显示历史。同一客户、同一产品的新日期会新增一条
记录，不会替换旧日期。选择任意两条日期可比较材料数量和工艺变化，也可导出全部历史。

旧版知识库第一次升级会在 `data/backups/` 自动保留迁移前备份；重复升级不会反复创建
同一迁移备份。

## Excel 导出

导出文件位于：

```
data/jobs/<job-id>/export/recognized-<job-id>.xlsx
```

可通过页面下载。Excel 按公司、产品、配方、材料、工艺参数等结构组织。

## 更新程序

### 稳定用户（推荐）

默认更新到最新稳定 Tag：

```powershell
.\install\update-windows.ps1
```

### 抢先体验用户

明确指定更新到 master：

```powershell
.\install\update-windows.ps1 -TargetRef master
```

### 更新前备份

更新前务必备份以下目录：

- `data/`（包含 settings、secrets、jobs、Excel、缓存）

### 更新完成后检查

```powershell
.\.venv\Scripts\python.exe scripts\doctor.py --full --json
```

退出码说明：
- `0` = READY
- `1` = SETUP_REQUIRED
- `2` = BROKEN

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

## 快速更新到最新稳定版

普通用户默认更新到最新稳定 Release Tag，不拉取尚未发布的 `master`。

### Windows Git 安装

在项目目录中运行现有安全更新器：

```powershell
.\install\update-windows.ps1
```

### Linux / macOS Git 安装

先备份 `data/`，再只切换到仓库中最高的稳定版本 Tag：

```bash
test -z "$(git status --porcelain --untracked-files=no)"
git fetch --tags --prune
stable_tag="$(git tag --list 'v[0-9]*.[0-9]*.[0-9]*' --sort=-v:refname | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | head -n 1)"
test -n "$stable_tag"
git switch --detach "$stable_tag"
```

随后按对应平台安装依赖并运行 `python scripts/doctor.py --full --json`。不要在普通更新中默认
切换到 `master`，也不要执行 `git reset --hard` 或 `git clean`。

### Windows EXE / macOS DMG 安装

设置页的“版本与更新”只推荐已发布、非预发布的稳定 Release。看到新版本后，从
[Releases](https://github.com/liumingyang-maker/daily-record-ocr-lite/releases) 下载对应平台的正式
签名安装器并覆盖安装；平台用户数据目录保持不变。

也可以把下面整段直接复制给 AI：

```text
请读取 AGENTS.md 和 docs/AI_AGENT_UPGRADE.md，把当前 daily-record-ocr-lite 安装安全更新到最新稳定 Release Tag。
更新前记录当前 commit/tag 并备份 data/；不得执行 git reset、git clean、删除用户配置或回显 API Key。
如果这是 Git 安装，自动选择最高的稳定 v主版本.次版本.修订版本 Tag；不得默认更新到 master 或预发布 Tag。
如果已是最新版，不要重复安装，只执行健康检查并报告。
实际更新后运行非 real_ocr 测试、至少一次真实 OCR 推理和 doctor --full。
最后输出 UPGRADE_REPORT，包括旧版本、新版本、备份位置、测试数量、真实 OCR、doctor 状态和回滚点。
```

完整步骤见 [`docs/AI_AGENT_UPGRADE.md`](docs/AI_AGENT_UPGRADE.md)。`master` 仅供用户
明确要求抢先体验时使用，不是普通更新的默认目标。

Windows x64 EXE 和 Apple Silicon macOS DMG 已在 [Draft PR #8](https://github.com/liumingyang-maker/daily-record-ocr-lite/pull/8)
通过未签名原生测试 Gate。普通用户仍应只从 **最新稳定 Release** 下载正式资产；文件名带
`UNSIGNED` 的 CI Artifact 仅供测试，可能触发 SmartScreen 或 Gatekeeper，不能描述为正式
无警告安装包。安装、升级、数据保留和签名/公证说明见
[`docs/DESKTOP_INSTALLERS.md`](docs/DESKTOP_INSTALLERS.md)。

## 常见问题

### 安装显示 SETUP_REQUIRED

**正常！** 这只是表示尚未配置视觉模型。访问 http://127.0.0.1:8765/setup 配置即可。

### Vision 测试成功但识别很慢

Qwen 完整任务约 90 至 120 秒，300 秒超时是预留安全时间。请耐心等待，不要重复提交。

### 状态是 REVIEW_REQUIRED

这是正常的安全状态，不是系统错误。进入配方卡片页面，对照证据确认每条配方，再将整批
确认结果加入知识库后，状态才会变为 READY。

### 无法导出 Excel

确认：
1. 状态是否为 `READY`
2. 是否还有待处理配方
3. 是否已点击“确认完成并加入知识库”并生成最终确认回执

### Qwen 连接失败

检查以下配置：
- Base URL：`https://dashscope.aliyuncs.com/compatible-mode/v1`
- Model：`qwen3.7-plus`
- API Key：`sk-ws` 按量 API Key
- 网络连接和系统代理
- **不要使用 Token Plan 端点**

### OCR 首次启动慢

首次加载 PP-OCRv6 模型属于正常情况，后续会使用本地缓存。

## Linux / macOS

Linux CPU：

```bash
./install/install-linux.sh
./start-linux.sh
```

macOS CPU：

```bash
./install/install-macos.sh
./start-macos.command
```

安装器接受：
- Doctor exit 0：READY
- Doctor exit 1：SETUP_REQUIRED

启动脚本只在配置完成后正常启动。

GPU 与 macOS 安装前必须查询 PaddlePaddle/PaddleOCR 当前官方兼容矩阵。详细入口见
[`install/README.md`](install/README.md) 和 `docs/INSTALL_*.md`。

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

### 开发与审计

- Qwen 超时审计：[`docs/audits/QWEN_FIVE_MINUTE_TIMEOUT_AUDIT.md`](docs/audits/QWEN_FIVE_MINUTE_TIMEOUT_AUDIT.md)

## 已知限制

手写质量、复杂表格和所选视觉模型会影响准确率；NVIDIA/macOS 的 Paddle 安装依赖
当前官方 wheel；v1 不支持绕过未确认项强制正式导出。本地应用默认只监听
`127.0.0.1`，不应直接暴露公网。
