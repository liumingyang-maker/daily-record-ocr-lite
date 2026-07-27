# Windows / macOS 桌面安装层 Draft 审计报告

> 本报告供独立 GPT 审核复制使用。审计范围仅限 `feat/desktop-installers` 相对
> `feat/evidence-first-product-workflow` 的增量。本分支保持 Draft，不合并、不打 Tag、
> 不创建 Release。

## 可直接复制给 GPT 的审计提示词

```text
请作为独立发布审计员审查 daily-record-ocr-lite 的桌面安装层 Draft PR。

审查目标：确认 Windows x64 与 macOS arm64 桌面安装实现是否满足“普通用户一键安装、
本机数据不随升级覆盖、仅绑定 127.0.0.1、正式资产必须签名、未经 Gate 不发布”的约束。

重点检查：
1. 平台数据目录与冻结资源目录是否彻底分离；升级是否会覆盖用户 data、jobs、知识库或密钥。
2. 旧数据导入是否只复制、不修改源目录；非空目标是否要求确认并先备份；是否阻止链接与目录穿越。
3. 单实例、动态端口、浏览器入口是否始终只绑定 127.0.0.1。
4. 三个官方 PP-OCRv6 模型是否经过归档 SHA-256、解压安全和逐文件 SHA-256 校验；失败是否可重试。
5. Windows Inno Setup、macOS DMG、PyInstaller spec 是否包含真实运行依赖；测试资产是否明确标记 UNSIGNED。
6. 正式工作流是否真实执行 Authenticode、Apple codesign、notarytool、stapler 和 Gatekeeper 校验；缺少凭据是否硬失败。
7. 稳定更新检查是否只选择已发布、非 prerelease、语义版本合法的稳定 Release。
8. 日志、测试、工作流和审计材料是否不含 API Key、Authorization、原始业务响应和用户数据。
9. 测试是否包含真实冻结程序的模型安装与 PP-OCRv6 推理，而不是 Mock 冒充。
10. 当前证据是否只足以保持 Draft，是否存在任何不应声称“正式安装包已发布”的缺口。

请按 P0/P1/P2 输出问题，逐条给出文件与行号；若无阻断问题，也要明确列出剩余发布前 Gate。
禁止仅根据本报告下结论，应同时审查 PR diff、GitHub Actions 日志和产物元数据。
```

## 1. 范围与状态

- 仓库：`liumingyang-maker/daily-record-ocr-lite`
- 基线分支：`feat/evidence-first-product-workflow`
- 实现分支：`feat/desktop-installers`
- 基线 SHA：`50e9039cd998403ffe7270e3f0b1f15eaae05b4e`
- 桌面实现 SHA：`fb7f1cf`
- Draft PR：创建后回填
- 合并：未执行
- Tag：未创建
- Release：未创建
- 用户运行目录：未修改

## 2. 实现摘要

- Windows 数据目录：`%LOCALAPPDATA%\DailyRecordOCR`
- macOS 数据目录：`~/Library/Application Support/DailyRecordOCR`
- 冻结资源从 PyInstaller `_MEIPASS` 读取，用户数据不写入应用安装目录。
- 旧数据导入不修改源目录；目标非空时要求显式确认，并创建同级备份。
- 桌面服务仅绑定 `127.0.0.1`，使用动态可用端口并执行单实例锁。
- 安装向导显示模型下载状态；三个模型全部校验成功前，桌面真实识别入口保持锁定。
- 稳定更新检查只接受 GitHub 已发布、非草稿、非预发布的稳定语义版本。
- Windows 使用 PyInstaller onedir + Inno Setup；macOS 使用 PyInstaller `.app` + DMG。
- PR 工作流仅上传文件名含 `UNSIGNED-TEST-ONLY` 的测试资产。
- 正式工作流是手动 Gate，缺少签名/公证凭据即失败，不会创建 Tag 或 Release。

## 3. 官方模型清单

| 模型 | 归档字节 | 归档 SHA-256 |
|---|---:|---|
| PP-LCNet_x1_0_textline_ori | 6,871,040 | `6171f69605215a85624d650e9079fa45f7c3eaf944296181bcc5395bf3ddc7f6` |
| PP-OCRv6_medium_det | 62,279,680 | `144d0621e059566e5086e228829171591c144c2deb07b2dad4962214fbabfcf7` |
| PP-OCRv6_medium_rec | 76,851,200 | `4eecc1c6a4623765042e6fc15446da0da110b7d875b6b72b2d351d2b2dbd4da6` |

总下载字节：146,001,920。归档校验后才解压；解压拒绝绝对路径、`..`、符号链接和硬链接；
安装完成后逐文件复核清单中的 SHA-256。

## 4. 本地验证证据

### 源码 Gate

- `python -m pytest -m "not real_ocr" -q`：359 passed，5 deselected。
- `python -m pytest -m real_ocr -q -s`：5 passed，359 deselected；真实推理 3 tokens，2500ms。
- `ruff check .`：All checks passed。
- `git diff --check`：通过。
- 源码 `--self-test`：OK，数据目录可写、单实例、仅回环地址。
- 源码 `--smoke-test`：OK，`http://127.0.0.1:<动态端口>/`。
- 源码 `--ocr-test`：OK，PP-OCRv6_medium，3 tokens，2217ms。

### Windows 冻结程序 Gate

- PyInstaller：6.21.0。
- 冻结程序：`DailyRecordOCR.exe` onedir 测试构建。
- `--self-test`：OK。
- `--smoke-test`：OK，仅 `127.0.0.1`。
- `--install-models`：READY，3/3，146,001,920 bytes。
- `--ocr-test`：OK，PP-OCRv6_medium，3 tokens，2171ms。
- 该结果来自真实 PaddleOCR 冻结进程，不是 Mock。

## 5. Secret 与隐私检查

- `git grep -n -E 'sk-(ws|sp)-[A-Za-z0-9._-]+'`：0 命中。
- `git diff | grep -E 'sk-(ws|sp)-[A-Za-z0-9._-]+'`：0 命中。
- 未提交 `data/settings.json`、`data/secrets.env`、`data/setup_health.json`、
  `data/connection-test.png`、`data/jobs/`、原始 API 响应或用户业务日志。
- 桌面后台模型下载错误只记录异常类型，不记录异常正文。

## 6. 原生 CI 与发布 Gate

- Windows x64 PR Gate：待 Draft PR 原生 CI 回填。
- macOS arm64 PR Gate：待 Draft PR 原生 CI 回填。
- Windows 正式签名 Gate：未执行，无正式签名资产。
- Apple Developer ID 签名、公证、staple、Gatekeeper Gate：未执行，无正式公证资产。
- Inno Setup 安装器未在本机 Windows 环境编译；由 Windows 原生 CI 验证。
- macOS DMG 无法在 Windows 本机生成；由 `macos-14` arm64 原生 CI 验证。

## 7. 公开文档依据

- GitHub 托管 runner：<https://docs.github.com/en/actions/reference/runners/github-hosted-runners>
- PaddlePaddle macOS pip 安装：<https://www.paddlepaddle.org.cn/documentation/docs/en/install/pip/macos-pip_en.html>
- PyInstaller spec：<https://pyinstaller.org/en/stable/spec-files.html>
- PyInstaller 6.21.0：<https://pypi.org/project/pyinstaller/>

## 8. 当前审计结论

本地源码 Gate 与 Windows PyInstaller 冻结程序 Gate 已通过，且 Secret 扫描为 0/0。
当前只能得出“实现已进入原生 CI 审核阶段”的结论。原生 Windows 安装器与 macOS DMG CI
未通过前，PR 必须保持 Draft；签名、公证、独立 GPT 审计和 Release Gate 未完成前，不得合并、
打 Tag 或发布正式资产。
