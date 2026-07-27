# daily-record-ocr-lite 个人版 v1.1.0 阶段审计

审计日期：2026-07-27  
审计状态：WIP / 禁止发布  
开发分支：`feat/personal-knowledge-layer`  
本报告输入 HEAD：`21be721cb9ebbf18a685c0d9fe72f225ef07eac6`

## 可直接复制给独立 GPT 的审查任务

```text
请独立审查 daily-record-ocr-lite 个人版阶段实现。

范围：
- 设计基线：docs/superpowers/specs/2026-07-27-personal-knowledge-system-design.md
- 实施计划：
  - docs/superpowers/plans/2026-07-27-personal-data-import.md
  - docs/superpowers/plans/2026-07-27-knowledge-assisted-recognition.md
  - docs/superpowers/plans/2026-07-27-personal-workbench-export.md
  - docs/superpowers/plans/2026-07-27-private-windows-release.md
- 代码范围：bb2c209..当前 feat/personal-knowledge-layer HEAD
- 阶段审计：docs/audits/PERSONAL_V1.1.0_WIP_AUDIT.md

重点检查：
1. 旧 Excel 提取是否保留数量原文、未知日期、注意事项、来源和证据；
2. 是否错误导入合同、报告、标签、成分表、__MACOSX 或空模板；
3. AI ZIP 是否能拒绝路径穿越、符号链接、重复/未声明文件、坏 JSONL、
   校验和错误、缺证据和擅自标准化数量；
4. 知识纠偏是否可能修改数量、日期、编号或跨客户错误自动纠正；
5. 用户确认配方、历史写入、词库学习是否共用事务并可回滚；
6. 未知日期是否允许正式确认并明确显示待补；
7. 证据文件服务是否限制在 data 根目录并核对 SHA-256；
8. 安装升级是否可能覆盖用户数据库或用户自己更换的 Key；
9. 是否存在 Secret、原始工作簿、原始模型响应或私人日志进入 Git；
10. 当前未完成 Gate 是否足以阻止 PR 合并、Tag 和 Release。

请按 P0/P1/P2 输出问题；每项给出文件、理由、可复现方法和建议修复。
若无阻塞问题，也必须列出残余风险。不要根据本报告直接相信“通过”结论，
请从代码和测试独立验证。
```

## 已完成范围

- 只读扫描 214 个文件：87 个候选配方工作簿，127 个排除文件。
- 支持 XLSX/XLS；排除 `__MACOSX`、非 Excel 和明确非配方业务文档。
- 结构化提取客户、产品、日期、材料、数量原文、工艺和注意事项。
- 同内容去重但保留全部来源、工作表、单元格和 tight/context 证据。
- SQLite v3 迁移、自动备份、事务导入、幂等回执、待确认和排除清单。
- 标准 AI ZIP 协议、Manifest Schema、安全预检、不可变预览和显式提交。
- 类型化词库检索、安全纠偏决策和确认后事务学习。
- 数量、日期、编号和配方号被列为禁止知识自动修改字段。
- 低置信 OCR 证据分为保留阈值和直接采用阈值。
- 配方卡片允许未知日期正式确认，并在历史中标记 `UNKNOWN`。
- 知识库可搜索客户/产品/日期，显示待确认资料及对应材料。
- 导入的工作表证据通过受限路径和 SHA-256 校验后展示。
- 个人种子首次安装与升级保留逻辑：已有数据库和用户 Key 不覆盖。
- GitHub 文档提供可复制的 AI 整理提示词和标准 ZIP 精确格式。

## 真实个人数据结果

- 正式配方：381
- 待确认：78
- 已知日期：170
- 未知日期：211
- 配方来源：385
- 证据 PNG：770
- 材料行：1909
- 工艺参数：1146
- 客户：58
- 产品：142
- 词库唯一词条：666
- 日期误入材料：0
- 无材料正式配方：0
- SQLite 外键错误：0
- `PRAGMA quick_check`：`ok`

当前本机数据库：
`C:\Users\97020\Desktop\daily-record-ocr-lite\data\knowledge.sqlite3`

替换前数据库保存在 `data/backups`；没有删除旧库或原始资料。

## 自动化验证

```text
focused legacy/package suite: 46 passed
current non-real suite: 424 passed, 5 deselected
Ruff: All checks passed
git diff --check: passed
tracked Secret scan: no match
working diff Secret scan: no match
```

AI ZIP 安全测试覆盖：

- 缺少证据；
- Manifest/文件 SHA-256 不一致；
- 未声明文件；
- 绝对路径和 `../`；
- 重复 ZIP 成员；
- ZIP 符号链接；
- 无效 JSONL；
- 错误配方标记；
- 禁止的 `normalized_amount`；
- 预检不写数据库；
- 显式提交后才事务导入。

## 本机运行状态

- 个人数据库已安全替换并备份旧库。
- 本机 `http://127.0.0.1:8765/` 和 `/knowledge` 返回 HTTP 200。
- 桌面源目录仍处于旧提交 `7023ea6`，且包含用户原有未提交代码修改。
- 为避免覆盖用户工作，新的页面和流水线代码尚未直接写回该脏目录。
- 正式切换必须通过后续私人 Windows 安装包完成。

## 尚未完成的发布 Gate

- 知识候选尚未完整接入每张配方卡片的 VLM Prompt、融合回执和局部复核。
- 配方卡片自动分割和真实多卡 A/B 基准尚未完成。
- 私人 Bundle 完整验证器、PyInstaller/Inno Setup 个人安装器尚未完成。
- 私人仓库尚未创建，任何私人数据均未推送 GitHub。
- 尚未对本分支执行真实 PP-OCRv6、真实 Qwen3.7 Plus 完整多卡任务。
- 尚未验证安装后的 FinalResult、确认入库和可下载 Excel 全链路。
- 尚未完成独立 GPT 最终审查、CI、私人 Tag 和 Release 资产校验。

因此当前明确禁止：

- 合并；
- Tag；
- Release；
- 宣称个人版安装包完成；
- 宣称知识辅助已通过真实准确率 Gate。

## Secret 与私人数据边界

- Git 中没有 `sk-ws` 或 `sk-sp` 真实 Key。
- API Key 不写入本报告、测试快照、PR 或公共日志。
- 原始 Excel、完整模型业务响应、任务日志和本机配置未加入 Git。
- 私人安装构建时只允许从进程环境或 Git 外私人输入读取 Key。
