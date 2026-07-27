# Windows 与 macOS 一键安装包

## 普通用户入口

只从 GitHub 的**最新稳定 Release**下载与系统匹配的正式资产：

- Windows 10/11 x64：`daily-record-ocr-lite-vX.Y.Z-windows-x64-setup.exe`
- Apple Silicon macOS 14+：`daily-record-ocr-lite-vX.Y.Z-macos-arm64.dmg`

正式 Release 尚未包含这些文件时，请继续使用 README 的源码安装方式，不要把源码 ZIP 当成安装包。
文件名含 `UNSIGNED` 的工作流 Artifact 是短期测试包，未完成 Windows Authenticode 或 Apple Developer ID
签名/公证，不能作为正式分发资产。

## 安装与启动

Windows：双击安装 EXE，可选创建桌面快捷方式。应用安装到当前用户目录，不要求管理员权限。
macOS：打开 DMG，把 `DailyRecordOCR.app` 拖到“应用程序”。Apple 公证不等于 App Store 上架；公证后的
DMG 仍从 GitHub Release 分发。

桌面入口不会显示终端窗口。应用只监听 `127.0.0.1`，自动选择未占用端口并打开浏览器。再次启动只会打开
已有实例。托盘菜单提供“打开应用”“系统检查”“退出”。

## 用户数据

- Windows：`%LOCALAPPDATA%\DailyRecordOCR`
- macOS：`~/Library/Application Support/DailyRecordOCR`

任务、知识库、OCR 模型缓存、设置和密钥与应用安装目录分离。覆盖升级和默认卸载不会删除这些数据。
源码版可在首次配置页的“高级设置 → 导入现有数据”选择旧项目或 `data` 目录；源目录保持不变，目标已有
内容时必须明确确认，程序会先创建完整备份。导入报告只记录类别和文件数量，不记录 Secret 内容。

## 更新

设置页的“版本与更新”只检查 GitHub 最新稳定 Release：

- 桌面安装版下载新 EXE/DMG 覆盖安装，不运行 Git；
- 源码安装版继续按 `docs/AI_AGENT_UPGRADE.md` 使用稳定 Tag 更新；
- `master` 不是普通用户默认更新目标。

## 卸载

默认卸载只移除应用文件和快捷方式，保留用户数据。当前安装器不提供静默清除用户数据的动作；如未来增加
显式清除选项，必须先验证目标路径确实位于上述平台数据根目录，且由用户单独确认。

## 构建者说明

构建依赖固定在 `requirements-desktop.txt`，使用 PyInstaller `onedir`：

```text
python -m pip install -r requirements-desktop.txt
python -m PyInstaller --noconfirm --clean packaging/desktop/daily_record_ocr.spec
```

Windows 使用 `packaging/windows/setup.iss` 和 Inno Setup 6；macOS 使用
`packaging/macos/build_dmg.sh`、`codesign`、`notarytool` 和 `stapler`。两个平台必须在对应原生 GitHub runner
构建，运行冻结后的 `--self-test`、`--smoke-test` 和 `--ocr-test`。最后一项必须得到真实 PP-OCRv6 token，
不得全部 skip。

PR 构建只上传名称含 `UNSIGNED` 的 7 天测试 Artifact。正式候选必须通过
`.github/workflows/desktop-release-gate.yml` 的 Secret Gate、签名、公证、staple、真实 OCR、SHA-256 和
构建来源证明；该工作流本身不创建 Tag 或 GitHub Release。

当前原生 runner 选择依据：GitHub 官方托管 runner 文档把 `macos-14` 列为 arm64；PaddlePaddle 官方
macOS 安装文档只支持 arm64 CPU，不再支持 x86_64。因此首版不生成 Intel Mac 安装包。
