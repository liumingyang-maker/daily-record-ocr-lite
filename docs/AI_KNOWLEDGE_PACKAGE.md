# 让 AI 整理历史配方并生成可导入 ZIP

本协议用于把混合资料交给其他 AI 整理，再生成
`daily-record-knowledge-package-v1` 标准 ZIP。系统先只读预检；只有用户明确
确认 `preview_id` 后才写入知识库。

## 可直接复制给 AI 的提示词

```text
你正在为 daily-record-ocr-lite 整理历史配方资料。

请读取我提供的文件，生成 daily-record-knowledge-package-v1 ZIP。
不要修改原文件，不要输出 SQLite，不要把 API Key、Authorization、账号或
完整原始业务响应写入包。

规则：
1. 只有结构明确的配方 Excel 记录进入 formulas.jsonl。
2. 报告、合同、标签、成分表、普通说明、PDF、Word 和无关图片进入
   excluded_files.jsonl，不得冒充配方。
3. 客户优先取一级文件夹名；产品优先取工作表名和配方标题。
4. 客户、产品、结构或日期归属冲突时写入 pending_review.jsonl，不得猜测。
5. 日期存在时存 YYYY-MM-DD；没有日期允许 record_date=null、
   date_status=UNKNOWN。
6. 数量只保留 amount_raw 原文；禁止补单位、换算或生成 normalized_amount。
7. 失败、废弃、作废、无效配方不进入正式历史；其中可靠的客户、产品、
   材料、工艺和专业注意事项词组可进入 lexicon.jsonl。
8. “通用配方”不保存配方，只提取可靠词条。
9. 完全相同记录可合并，但 provenance.jsonl 必须保留全部来源、工作表、
   单元格和证据。
10. 每条正式配方必须有 tight 和 context 两张必要证据 PNG；不要包含完整
    原始 Excel。

ZIP 顶层直接包含：
manifest.json
formulas.jsonl
lexicon.jsonl
provenance.jsonl
pending_review.jsonl
excluded_files.jsonl
validation_report.json
checksums.sha256
evidence/

所有文本用 UTF-8，JSONL 每行一个 JSON 对象。manifest 声明除
manifest.json、checksums.sha256 外的每个文件及 path、sha256、size。
checksums.sha256 每行格式是“<64位小写摘要><两个空格><相对路径>”，覆盖
manifest.json 和全部声明文件，不覆盖自身。

禁止绝对路径、反斜杠、..、符号链接、未声明文件和重复路径。
validation_report.json 必须为
{"status":"PASS","errors":[],"warnings":[...]}。
最终只交付 ZIP 和不含业务原文的数量汇总。
```

## ZIP 目录

```text
knowledge-package.zip
├─ manifest.json
├─ formulas.jsonl
├─ lexicon.jsonl
├─ provenance.jsonl
├─ pending_review.jsonl
├─ excluded_files.jsonl
├─ validation_report.json
├─ checksums.sha256
└─ evidence/
   ├─ <formula-id>-tight.png
   └─ <formula-id>-context.png
```

ZIP 内不要再套一层目录。

## 精确数据格式

Manifest Schema：
[`config/schema/knowledge-package-v1.schema.json`](../config/schema/knowledge-package-v1.schema.json)。

`manifest.json`：

```json
{"schema_version":"daily-record-knowledge-package-v1","package_id":"customer-history-20260727-v1","created_at":"2026-07-27T09:00:00Z","files":[{"path":"formulas.jsonl","sha256":"<64位小写SHA-256>","size":1234}]}
```

`formulas.jsonl` 每行：

```json
{"record_type":"FORMULA","formula_id":"formula-0001","customer":"示例客户","product":"G30A","record_date":"2024-07-12","date_status":"KNOWN","formula_label":"配方1","materials":[{"name_raw":"PA6","amount_raw":"55"},{"name_raw":"玻纤","amount_raw":"45%"}],"process":[{"name_raw":"主机","value_raw":"465"}],"notes_raw":"保持黑度"}
```

无日期时 `record_date` 必须为 `null`，`date_status` 必须为 `UNKNOWN`。

`lexicon.jsonl` 每行：

```json
{"term_type":"material","standard_value":"玻纤","aliases":["玻璃纤维"],"source_quality":"confirmed"}
```

`term_type` 只能是 `customer`、`product`、`material`、`process`、
`note_phrase`；`source_quality` 只能是 `reference`、`candidate`、
`confirmed`。

`provenance.jsonl` 每行：

```json
{"formula_id":"formula-0001","source_file":"示例客户/历史配方.xlsx","sheet_name":"G30A","cell_range":"A2:D6","evidence":["evidence/formula-0001-tight.png","evidence/formula-0001-context.png"]}
```

`pending_review.jsonl`：

```json
{"reason":"PRODUCT_CONFLICT","payload":{"sheet_product":"G30A","title_product":"G30B"}}
```

`excluded_files.jsonl`：

```json
{"source_file":"示例客户/合同.pdf","reason":"NON_FORMULA_DOCUMENT"}
```

## 本机预检与确认导入

先预检。此命令不写数据库：

```powershell
.\.venv\Scripts\python.exe scripts\import_personal_history.py validate-package `
  --package C:\path\knowledge-package.zip `
  --data-dir .\data `
  --report .\data\personal_imports\package-preview.json
```

检查报告中的数量和 `preview_id` 后，再明确提交：

```powershell
.\.venv\Scripts\python.exe scripts\import_personal_history.py commit-package `
  --preview-id <64位preview_id> `
  --data-dir .\data `
  --database .\data\knowledge.sqlite3
```

系统在提交时再次校验。重复提交同一包返回同一结果。

## 强制拒绝条件

- 缺证据或来源；
- 推测、换算数量或加入 `normalized_amount`；
- 正式配方缺客户、产品或材料；
- JSON/JSONL 无效；
- Manifest、大小或 SHA-256 不匹配；
- ZIP 含绝对路径、`..`、反斜杠、符号链接、重复或未声明文件；
- `validation_report.json` 不是 PASS；
- 预检后内容被修改。
