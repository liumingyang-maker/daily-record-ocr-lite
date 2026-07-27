# Windows与macOS一键安装包设计

- 日期：2026-07-27
- 状态：已完成会话设计确认，等待用户审阅书面规格
- 依赖：`2026-07-27-evidence-first-product-workflow-design.md`完成并通过应用Gate
- 交付方式：独立Draft PR，不与网页和知识库大改混为一个PR

## 1. 背景与目标

现有安装入口仍要求用户预装Python和Git，再运行PowerShell或Shell脚本。GitHub Release只有源码ZIP，不是普通用户理解的一键安装产品。

本规格提供两个不要求预装Python或Git的CPU桌面安装包：Windows x64安装EXE和Apple Silicon macOS DMG。安装后用户从桌面、开始菜单或应用程序目录启动，程序在本机启动Web服务并自动打开浏览器。升级和默认卸载必须保留任务、知识库、模型缓存、设置和私密配置。

## 2. 非目标

- 不支持Windows ARM、Intel Mac、Mac GPU或其他未通过真实OCR Gate的平台。
- Windows GPU继续使用现有高级安装脚本，不自动猜测CUDA版本。
- 首版不提供静默自动更新；只检查稳定版并引导用户下载新版安装包覆盖安装。
- 不把未签名测试包描述为无警告的正式安装包。
- 不上架Mac App Store；签名和公证后的DMG仍从GitHub Release分发。

## 3. 支持范围

| 平台 | 架构 | OCR | 交付物 |
|---|---|---|---|
| Windows 10/11 | x64 | PaddleOCR CPU | `daily-record-ocr-lite-vX.Y.Z-windows-x64-setup.exe` |
| macOS 14及以上 | Apple Silicon arm64 | PaddleOCR CPU | `daily-record-ocr-lite-vX.Y.Z-macos-arm64.dmg` |

PaddlePaddle 3.3官方macOS wheel只支持arm64且仅支持CPU，因此不生成Intel Mac包。任何平台只有在安装后的真实PP-OCRv6推理通过后，才能被列为正式支持。

## 4. 打包结构

使用固定版本的PyInstaller `onedir`模式分别在Windows x64和macOS arm64原生环境构建。不使用启动时反复解压的大型`onefile`模式，也不跨平台构建。Windows用Inno Setup 6生成安装EXE；macOS用系统`hdiutil`生成DMG，并在正式构建中使用`codesign`、`notarytool`和`stapler`完成签名公证链。

安装包包含：

- Python运行时。
- FastAPI应用、模板、静态文件、Schema和默认配置。
- 固定版本的PaddlePaddle、PaddleOCR、OpenCV及核心依赖。
- 桌面启动器和doctor。

PP-OCRv6模型使用带版本和SHA-256的模型清单，在安装完成后的首次启动中下载到用户数据目录。页面显示下载进度、当前模型和失败后的重试入口。模型下载或校验未完成时，真实识别保持锁定；后续版本使用同一模型版本时复用缓存。

Windows使用安装器封装`onedir`产物，建立开始菜单和可选桌面快捷方式。macOS把同一启动入口封装为`.app`并放入DMG，用户拖入“应用程序”后启动。

## 5. 桌面启动器

桌面快捷方式不暴露终端窗口。启动器负责：

1. 获取单实例锁；重复启动时只打开已有页面。
2. 仅在`127.0.0.1`启动服务。
3. 默认端口被其他程序占用时选择可用端口，并记录到当前实例状态。
4. 打开默认浏览器。
5. 使用固定版本的`pystray`提供托盘菜单“打开应用”“系统检查”“退出”，退出时停止本地服务。
6. 首次启动进入中文配置向导；模型或视觉配置未完成时保持`SETUP_REQUIRED`。

## 6. 用户数据与源码兼容

安装目录只保存可替换的程序文件。用户数据默认放在：

- Windows：`%LOCALAPPDATA%\DailyRecordOCR`
- macOS：`~/Library/Application Support/DailyRecordOCR`

应用的数据路径解析顺序固定为：显式`DAILY_RECORD_OCR_DATA_DIR`、桌面安装平台目录、源码运行的项目`data/`。这样桌面安装版和源码版共用服务代码，但不会误写安装目录。

首次启动提供“导入现有安装数据”。用户选择旧源码项目目录后，迁移器验证其确实包含本项目的数据结构，再把任务、知识库、设置、私密配置和可用模型缓存复制到平台数据目录。迁移不删除或修改旧目录；目标目录非空时先创建备份并要求用户明确确认，不能静默覆盖。迁移过程只记录文件类别、数量和脱敏错误，不记录Secret内容。

安装包、日志、崩溃信息和诊断输出不得复制或显示API Key。现有源码安装脚本与启动入口继续保留，作为开发者、高级用户和故障恢复路径。

## 7. 安装、升级与卸载

Windows新版安装器使用稳定应用ID覆盖程序文件；macOS用新版`.app`替换旧应用。两者都不得删除平台数据目录。

卸载默认保留全部用户数据。只有用户明确选择“同时删除我的任务和知识库”后，卸载器才允许清理已经解析并验证位于平台数据根目录内的文件；不得对未验证路径执行递归删除。

设置页增加“版本与更新”：显示当前版本、检查最新稳定Release并打开下载页。README和AI升级协议必须先识别桌面安装版或源码版；桌面安装版只使用新版安装包覆盖更新，不执行Git更新器。

## 8. 签名、公证与发布分级

开发阶段允许CI生成：

- 未签名Windows测试安装包。
- 未签名macOS测试DMG。

这些文件只作为工作流Artifact或明确标记的预发布资产。未签名DMG可能触发Gatekeeper；未签名EXE可能触发SmartScreen，文档必须如实说明。

正式macOS Release资产必须使用Developer ID签名，启用Hardened Runtime，提交Apple公证并把凭证staple到DMG。证书和公证凭据只存入GitHub加密Secrets。Secrets缺失时允许完成测试构建，但正式macOS发布Gate必须阻止上传。

Windows Authenticode签名作为正式分发的推荐Gate。证书未配置时允许生成个人测试安装包，但不得把它描述为无警告安装。

Apple公证不是Mac App Store审核；公证后的DMG继续通过GitHub Release直接分发。

## 9. 原生构建和安装Gate

桌面包只能由对应原生GitHub Actions runner构建：

- Windows x64 runner构建和安装EXE。
- macOS arm64 runner构建、挂载和安装DMG。

每个平台必须在干净环境完成：

1. 依赖版本和模型清单校验。
2. PyInstaller收集检查，禁止静默缺失动态库或资源。
3. 安装、首次启动、单实例和端口冲突测试。
4. `/health`与doctor验证；`BROKEN`直接失败。
5. 至少一次真实PP-OCRv6推理，不能全部skip。
6. 覆盖升级后原任务、知识库和配置仍可读取。
7. 默认卸载后数据仍存在；显式清理只删除目标数据目录。
8. 生成SHA-256与GitHub构建来源证明。
9. macOS正式任务验证签名、公证和staple结果。

任一平台未通过自己的Gate时，不发布该平台资产，也不得用源码包替代后声称一键安装完成。

## 10. Release资产

正式Release包括：

- Windows x64安装EXE。
- macOS arm64 DMG；只有签名和公证Gate通过后才作为正式资产。
- 源码ZIP。
- `SHA256SUMS.txt`。
- 构建来源证明。
- 安装说明、升级说明和脱敏审计报告。

版本号和Tag只在全部必需Release Gate通过后更新和创建。本规格实现阶段只建立可重复构建和测试的Draft PR，不自行合并、Tag或发布。

## 11. 测试策略

按TDD覆盖：数据目录解析、旧源码数据导入、冻结资源定位、单实例、动态端口、模型清单和哈希、下载中断重试、更新检查、升级保留数据、卸载保护和Secrets缺失时的发布阻断。

CI之外还需要在至少一台真实Windows 10/11 x64机器和一台真实Apple Silicon Mac上完成安装、首次模型下载、启动、视觉配置、真实OCR、退出、再次启动、覆盖升级和卸载验证。测试使用私密配置，不把API Key、完整业务响应或用户图片写入公共日志。

## 12. 验收标准

- Windows 10/11 x64用户无需预装Python或Git即可安装、启动和卸载CPU版应用。
- Apple Silicon macOS用户无需预装Python或Git即可安装、启动和卸载CPU版应用。
- 桌面快捷方式启动时不出现终端窗口，重复启动不会产生多个服务实例。
- 应用只监听本机回环地址，端口冲突不会导致无解释失败。
- 首次模型下载有进度、SHA-256校验和重试；模型不完整时真实识别保持锁定。
- 用户可把现有源码安装的数据复制到桌面版；原目录保持不变，冲突前有备份和明确确认。
- 覆盖升级和默认卸载不会删除任务、知识库、模型缓存或私密配置。
- 两个平台安装产物分别通过原生环境的health、doctor和真实OCR Gate。
- 未签名测试包与正式签名、公证资产明确分级，不误导用户。
- macOS缺少Developer ID Secrets时，正式DMG发布Gate必定失败。
- Release资产包含校验和、来源证明和可复制的脱敏审计报告。
