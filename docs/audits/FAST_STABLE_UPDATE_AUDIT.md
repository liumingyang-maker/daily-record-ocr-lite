# 最新稳定版快速更新审计报告

## 一键复制给 GPT 审查

```text
请作为独立软件变更审计员，审查 daily-record-ocr-lite 的“最新稳定版快速更新”变更。

仓库：
https://github.com/liumingyang-maker/daily-record-ocr-lite

分支：
docs/fast-stable-update

固定比较点：
ce410bf6d539288fa3e6c4114fb200ab4c6cc145...HEAD

设计：
docs/superpowers/specs/2026-07-24-fast-stable-update-design.md

实施计划：
docs/superpowers/plans/2026-07-24-fast-stable-update.md

请核验：
1. Windows 更新器默认选择最高的稳定 v主版本.次版本.修订版本 Tag，并排除预发布 Tag。
2. Tag 使用 detached checkout 且不执行 git pull；分支只允许 pull --ff-only。
3. 更新前保护工作区、备份 data/，禁止 reset、clean 和数据删除。
4. README 提供可直接复制给 AI 的快速更新提示词。
5. AI 升级协议覆盖 Windows、Linux、macOS、非 Git 安装、验证和 UPGRADE_REPORT。
6. 普通用户不默认更新 master。
7. 没有修改 OCR、Pipeline、配置格式或用户数据。
8. 测试、Secret 扫描和审计证据是否准确。

输出：
- 阻塞/严重问题
- 重要问题
- P2/轻微问题
- 项目规范结论
- 设计符合性结论
- 是否建议合并

每项发现必须提供文件和行号。不要输出或索取 API Key。
```

## 审计元数据

- 固定点：`ce410bf6d539288fa3e6c4114fb200ab4c6cc145`
- 分支：`docs/fast-stable-update`
- 设计提交：`4493657`
- 计划提交：`188903e`
- 测试提交：`5e1d4cb`
- 更新器提交：`7ab22c0`
- README/协议提交：`b64817d`
- 审查修复提交：`c6b8f03`
- 审计日期：2026-07-24

## 变更范围

- `install/update-windows.ps1`
  - 默认 `Ref=latest`。
  - 只从当前 `origin` 选择严格稳定语义版本 Tag，不信任本地自建 Tag。
  - Tag 走 detached checkout；分支只走 `pull --ff-only`。
  - 保留工作区检查、`data/` 备份和加固安装器。
  - 已是最新版时先运行 `doctor --json --gate`；环境缺失时继续修复安装。
  - 输出旧版本、目标版本、备份路径和回滚 commit。
- `README.md`
  - 增加“快速更新到最新稳定版”入口。
  - 增加可直接复制给 AI 的升级提示词。
- `docs/AI_AGENT_UPGRADE.md`
  - 明确稳定 Tag、三平台、非 Git 安装、验证和 `UPGRADE_REPORT`。
- `tests_lite/test_v1_contracts.py`
  - 增加更新器和文档静态契约。

未新增 Linux/macOS 更新脚本，未修改 OCR、Pipeline、Fusion、FinalResult、配置格式或
`data/` 内容。

## TDD 与本地验证

- RED：新增契约首次运行结果为 `2 failed, 1 passed`。
- GREEN：目标契约结果为 `3 passed, 30 deselected`。
- 审查 RED：origin Tag 来源与同版本 doctor 强化契约首次失败。
- 审查 GREEN：强化契约通过，真实 `git ls-remote origin` 返回 `v1.0.1`、`v1.0.0`。
- PowerShell Parser：语法通过。
- 稳定 Tag 解析：当前选择 `v1.0.1`。
- `ruff check .`：通过。
- `git diff --check`：通过。
- `python -m pytest -m "not real_ocr" -q`：`249 passed, 5 deselected`。
- 跟踪内容 Secret 扫描：无匹配。
- 相对固定点 diff Secret 扫描：无匹配。

更新器未在当前开发工作树中执行真实 checkout，因为这会破坏正在审查的分支。Tag
选择、条件分支和禁止命令由静态契约覆盖；真实 Windows 安装尚待 PR CI 验证。

## 安全与失败策略

- 跟踪工作区非干净时停止。
- 不执行 `git reset`、`git clean`、强制 checkout 或数据删除。
- 版本切换前备份 `data/`。
- 不在报告中读取或输出 API Key、Authorization Header 或本机配置。
- 失败时保留备份和旧 commit，不自动覆盖或恢复用户数据。
- 非 Git 安装采用新目录并保留旧安装作为回滚点。

## 已知限制

- Linux/macOS 本次只有 AI 协议，没有自动更新脚本。
- 更新器行为已通过静态契约验证；真实 Windows checkout/安装路径尚待 PR CI。
- `master` 仍可由用户显式传入，但不再是普通用户默认目标。

## 独立 GPT 审查

### 项目规范

首次审查发现：

1. **严重，已修复**：旧实现从全部本地 Tag 选最高版本，可能误选本地自建
   `v999.0.0`。现改为通过 `git ls-remote ... origin` 读取当前远端 Tag，再进行稳定
   版本过滤和排序。
2. **重要，已修复**：同版本路径直接退出，未执行健康检查。现优先运行
   `.venv` 的 `doctor --json --gate`；doctor 失败即停止，环境缺失则继续修复安装。
3. **重要，已处置**：审查时本报告尚未跟踪。复核结论现已回填，本报告随审计提交进入
   分支和 PR。
4. **P2，部分加固并接受剩余限制**：静态测试原先只检查字符串。现增加 origin-only
   和同版本 doctor 的代码块约束；当前分支仍不执行破坏性的真实 checkout，最终由
   Windows PR CI 验证安装路径。

### 设计符合性

设计审查将本地 Tag 来源问题评为重要，规范审查将其评为严重；同版本健康检查均评为
重要。两项均已在 `c6b8f03` 修复。修复后双轴复核均未发现剩余阻塞、严重或重要问题，
也未发现 OCR、Pipeline、Linux/macOS 自动脚本或其他范围漂移。

## 当前结论

独立 GPT 双轴复核通过，首次发现的严重/重要实现问题已修复，仅保留真实 Windows
checkout/安装待 PR CI 的 P2。建议进入 PR；在 CI 完成前不作最终合并结论。
