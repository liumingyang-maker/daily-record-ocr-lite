# 最新稳定版快速更新设计

## 目标

让普通用户和安装 AI 默认更新到最新稳定 Release Tag，而不是尚未发布的 `master`。
更新必须保护 `data/`、用户配置和 API Key，并提供可验证、可回滚的结果。

## 范围

本次修改：

- README 增加醒目的“快速更新到最新稳定版”入口和可复制 AI 提示词。
- 最小修正现有 `install/update-windows.ps1`，使其可靠支持自动选择最新稳定 Tag。
- 完善 `docs/AI_AGENT_UPGRADE.md` 的 Windows、Linux 和 macOS 更新步骤。
- 增加 Windows 更新器的静态契约测试。
- 生成可复制审计报告并交给独立 GPT 复核。

本次不新增 Linux/macOS 更新脚本，不修改 OCR、Pipeline、配置格式或数据结构。

## 稳定版本选择

“最新稳定版”必须严格匹配：

```text
^v[0-9]+\.[0-9]+\.[0-9]+$
```

RC、beta、alpha 和其他预发布 Tag 不得被默认选择。候选 Tag 使用 Git 的版本排序，
选择最高版本。用户仍可显式传入 `master`、具体 Tag 或其他合法 Ref。

## Windows 更新器

`install/update-windows.ps1` 的默认 `Ref` 改为 `latest`：

1. 检查跟踪工作区是否干净；不得执行 `reset` 或 `clean`。
2. 备份整个 `data/` 到带时间戳的 `backups/`。
3. 执行 `git fetch --tags origin`。
4. 当 `Ref=latest` 时解析最新稳定 Tag；没有稳定 Tag 时明确失败。
5. 当目标是 Tag 时执行 detached checkout，不运行 `git pull`。
6. 当目标是分支时 checkout 后执行 `git pull --ff-only origin <branch>`。
7. 调用现有 Windows 安装器更新依赖并执行 doctor Gate。
8. 输出旧版本、目标版本、备份路径和最终状态。

显式 `-Ref master` 的现有用法继续有效。

## README 快速入口

README 在项目简介后增加“快速更新到最新稳定版”：

- Windows 用户提供单条更新命令。
- Linux/macOS 用户引导 AI 按升级协议执行。
- 提供一个可直接复制给 AI 的完整提示词。
- 提示词要求读取 `AGENTS.md` 和 `docs/AI_AGENT_UPGRADE.md`。
- 明确禁止删除 `data/`、执行 `reset/clean`、回显 API Key 或使用 Mock 冒充验收。
- 要求输出 `UPGRADE_REPORT`。

## AI 升级协议

AI 必须执行：

1. 记录操作系统、当前 commit/tag、Python 和工作区状态。
2. 确认远端仓库并 fetch Tags。
3. 解析最新稳定 Tag；若已是最新版，不重复安装，只运行快速健康检查并报告。
4. 更新前备份 `data/`，记录可回滚的旧 commit/tag。
5. Windows 使用更新器；Linux/macOS 按协议 detached checkout Tag 后调用现有安装器。
6. 实际更新后运行：
   - `python -m pytest -m "not real_ocr" -q`
   - `python -m pytest -m real_ocr -q -s`，至少一个真实推理通过
   - `python scripts/doctor.py --full --json`
7. 若失败，停止继续操作，保留备份和旧版本信息，不自动恢复或覆盖用户数据。

`UPGRADE_REPORT` 必须包含旧版本、新版本、目标 Tag、备份位置、依赖更新、测试数量、
真实 OCR 结果、doctor 状态、失败项和回滚点；不得包含 Secret。

## 测试

增加静态契约测试，至少覆盖：

- 默认 Ref 为 `latest`。
- 稳定 Tag 过滤规则排除预发布版本。
- Tag 路径不执行 `git pull`。
- 分支路径只允许 `--ff-only`。
- 更新前仍执行工作区检查和 `data/` 备份。
- 脚本不包含 `reset`、`clean` 或数据删除。
- README 和 AI 升级协议包含最新稳定 Tag、数据保护及 `UPGRADE_REPORT` 要求。

完整 Gate：

```text
ruff check .
git diff --check
python -m pytest -m "not real_ocr" -q
```

## 审计与交付

变更完成后在 `docs/audits/` 生成脱敏、可复制的审计报告，并由独立 GPT 分别审查项目
规范和本设计符合性。所有严重或重要发现必须修复或明确阻塞后才能合并。

最终交付包括 README 链接、升级协议、更新器测试结果、Commit/PR/CI 和审计结论。
