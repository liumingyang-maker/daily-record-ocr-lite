# AI Agent 升级指南

## 默认升级策略

普通用户只更新到最新稳定 Release Tag。稳定 Tag 必须严格匹配：

```text
^v[0-9]+\.[0-9]+\.[0-9]+$
```

不得默认选择 alpha、beta、RC、其他预发布 Tag 或尚未发布的 `master`。只有用户明确
要求抢先版本时，才允许把 `master` 作为目标。

## 升级前检查

AI 必须先执行并记录：

```text
git status --porcelain
git remote get-url origin
git rev-parse HEAD
git describe --tags --exact-match
python --version
```

要求：

1. 跟踪工作区存在修改或未跟踪文件时停止，不得覆盖用户工作。
2. 不得执行 `git reset`、`git clean`、强制 checkout 或删除 `data/`。
3. 不得读取、打印或写入报告中的 API Key、Authorization Header 和本机配置内容。
4. 更新前记录旧 commit/tag，并把整个 `data/` 复制到带时间戳的 `backups/`。
5. 记录 `origin` 地址；仓库来源异常时停止并报告。

## 解析最新稳定 Tag

Git 安装必须先执行：

```text
git fetch --tags origin
```

然后按 Git 版本倒序排列 Tag，只保留符合
`^v[0-9]+\.[0-9]+\.[0-9]+$` 的项目并选择第一项。必须同时解析目标 commit：

```text
git rev-list -n 1 <latest-stable-tag>
```

如果当前 commit 与目标 commit 相同，不要重复安装。只运行 doctor 和必要健康检查，
然后输出“已是最新稳定版”。

## Windows 快速更新

在 Git 仓库根目录运行：

```powershell
.\install\update-windows.ps1
```

更新器默认解析最新稳定 Tag、备份 `data/`、以 detached HEAD 切换到该 Tag，并复用
加固后的 Windows 安装器。指定稳定版本可以使用：

```powershell
.\install\update-windows.ps1 -Ref v1.0.1
```

只有用户明确要求时才使用：

```powershell
.\install\update-windows.ps1 -Ref master
```

GPU 用户继续传入：

```powershell
.\install\update-windows.ps1 -OcrMode Gpu -PaddleInstallCommand "经过官方文档确认的安装命令"
```

`-SkipOcr` 只允许用于显式 Demo/开发环境，不能作为真实升级验收。

## Linux 与 macOS

Linux/macOS 本次不新增自动更新器。AI 必须执行等价的安全步骤：

```text
1. 确认工作区干净并记录旧 commit/tag。
2. 创建 backups/data-<timestamp>/，复制 data/ 的全部内容。
3. 运行 git fetch --tags origin。
4. 解析最高的稳定语义版本 Tag。
5. 运行 git checkout --detach <latest-stable-tag>。
6. Linux 运行 bash ./install/install-linux.sh。
7. macOS 核对 PaddlePaddle/PaddleOCR 当前官方兼容矩阵，再运行
   bash ./install/install-macos.sh --paddle-install-command "<官方安装命令>"。
```

不得对 Tag 执行 `git pull`。忽略的用户配置保留在 `data/`，不得因 detached checkout
而删除或覆盖。

## 非 Git 安装

如果当前目录没有 `.git`，不得直接运行 Git 命令。AI 应下载最新稳定 Release 的源码
ZIP 到新目录，保留旧安装作为回滚点，备份并迁移 `data/`，执行对应平台安装器，完成
全部验证后再切换启动入口。不得原地覆盖旧目录。

## 更新后 Gate

实际发生版本更新后必须运行：

```text
python -m pytest -m "not real_ocr" -q
python -m pytest -m real_ocr -q -s
python scripts/doctor.py --full --json
```

真实 OCR 必须至少有一个推理通过，不能全 skip。doctor 为 `BROKEN` 时升级失败，不得
启动生产识别或声称完成。

失败时停止后续操作，保留数据备份、旧 commit/tag 和旧安装目录。不得自动回滚或自动
覆盖用户数据；应向用户报告安全的人工回滚点。

## UPGRADE_REPORT

AI 最终必须输出：

- 操作系统与架构。
- Python 版本。
- 旧 commit/tag。
- 目标最新稳定 Tag 与新 commit。
- 数据备份位置。
- 核心、PaddlePaddle、PaddleOCR 和 OpenCV 依赖操作。
- 非 real OCR 测试通过数。
- 真实 OCR 测试通过数，确认非全 skip。
- doctor 状态与应用 URL。
- 是否已是最新版。
- 失败命令、退出码和脱敏错误。
- 可人工使用的回滚 commit/tag 或旧安装目录。

报告不得包含 API Key、Authorization Header、`data/secrets.env` 内容或其他 Secret。
