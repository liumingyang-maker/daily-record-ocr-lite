# PR #9 独立审查整改审计（WIP）

> 状态：**阻塞 / 保持 Draft / 禁止 Merge、Tag、Release**
> 日期：2026-07-27
> 分支：`feat/personal-knowledge-layer`
> PR：https://github.com/liumingyang-maker/daily-record-ocr-lite/pull/9

## 可直接复制给独立 GPT 的复核提示词

```text
请独立审查 daily-record-ocr-lite PR #9 的最新实际 Diff，不要只复述本报告。

重点验证：
1. Knowledge 是否已进入 VLM Prompt、类型化上下文检索、安全 Fusion 和 FinalResult；
2. knowledge_trace 是否完整、可逆且符合 record-v1 Schema；
3. amount/date/formula_no/unit 是否绝不被历史知识自动覆盖；
4. 知识候选是否只有在唯一高分、分差足够、客户/产品上下文一致且有图像/OCR证据时才自动纠正；
5. Qwen3.7 Plus 大图缩放是否只作用于阿里云 qwen3.7-plus，是否存在精度或格式回归；
6. ZIP路径安全、证据路径/SHA、非配方Excel排除、升级保留数据库/settings/Key的测试是否真实覆盖实现；
7. 根据真实 A/B/C 证据判断 PR 是否仍应保持 Draft。
8. 最新实现是否保持整图 OCR/VLM，只把裁剪用于人工审查；证据路由是否按
   Job/formula 身份、受限路径与 source/crop SHA-256 fail-closed；
9. `24.7.19`、`22/9/27` 等日期是否保留原文，同时只派生 ISO 排序值；
   UNKNOWN/UNPARSED 是否不会被历史知识或迁移静默改写；
10. sticky 证据是否真正受当前配方卡片约束，窄屏是否取消 sticky 且无横向滚动。

请输出 P0/P1/P2、Secret/私人数据边界、是否允许 Ready、是否允许 Merge。
真实 Knowledge ON 已生成 structured_result 和 FinalResult，但 OFF 对照失败，
且用户尚未确认问题字段、未生成正式 Excel；禁止给出允许发布结论。
```

## 2026-07-27 配方裁剪证据与日期排序整改（最新）

### 审计范围

- 设计：`docs/superpowers/specs/2026-07-27-sticky-cropped-evidence-and-date-sorting-design.md`
- 实施计划：`docs/superpowers/plans/2026-07-27-sticky-cropped-evidence-and-date-sorting.md`
- 实现提交：`c3e78ec`、`fd48d0d`、`06f80f3`、`a2836b5`、`3ebb7df`、`0e900b7`
- 实现 HEAD：`0e900b7`（本审计文档提交不计入实现范围）

### 已完成代码整改

- OCR 和 Qwen 继续读取整图；没有改成逐配方重复调用模型。
- Qwen 紧凑合同新增可选归一化 `record_bbox`，Prompt 明确其只用于审查定位。
- 新增本地 `FormulaEvidenceResolver`：融合模型 bbox、OCR 配方号/日期/材料锚点、
  来源顺序安全分区；重复词命中偏离分区时回退较大安全区域或整图。
- 裁剪从原始上传图生成高质量 JPEG；`review/evidence_regions.json` 绑定 formula ID、
  source image、归一化/像素区域、定位来源、原图 SHA-256 和裁剪 SHA-256。
- 证据 API 不接受任意文件路径；只按现存 Job/formula ID 查 manifest，要求路径仍在
  Job 的 `source/` 或 `review/evidence/` 范围内，并同时核对原图和裁剪 hash。
- 审查页左侧显示当前配方裁剪，保留“查看整图”；桌面 sticky 只在当前卡片内生效，
  小于等于 900px 改为单列静态证据；没有显示“裁剪待确认”文案。
- 日期控件改为文本输入。FinalResult、UI、Excel 继续保留原写法；统一解析器只派生
  ISO 排序值，支持两位/四位年份和 `.`、`/`、`-`，两位年份按 `20xx`。
- SQLite v4 迁移新增 `record_date_raw`，现有 `record_date` 作为内部 ISO 排序列；
  非空非法值保留原文、排序值置空并标记 `UNPARSED`，迁移前自动备份。
- 同一来源中夹在两个已知日期之间的无日期记录按 `source_order` 保持中间位置，
  不为其编造日期；无锚点时使用录入时间和来源顺序稳定排序。

### TDD 与自动化证据

| Gate | 结果 |
|---|---|
| 日期解析/编辑定向测试 | 18 passed |
| 知识迁移/历史/页面定向测试 | 29 passed |
| 裁剪/API/Pipeline/Knowledge 定向测试 | 41 passed |
| 全量非真实测试 | **480 passed, 5 deselected** |
| Ruff | `python -m ruff check lite_app tests_lite scripts` 通过 |
| Diff check | 通过 |
| tracked Secret scan | 0 match |
| working diff Secret scan | 0 match |

### 真实两图审查证据 Gate

使用已有成功 Job `20260727-200552-b00c4a` 的持久化 OCR、FinalResult 和两张原图
离线生成审查证据，没有重新调用模型、没有覆盖识别结果：

- 2 张原图、7 条配方均生成独立 manifest 项和 JPEG；定位来源均为 `local`。
- 第 1 页 5 条配方使用来源顺序安全分区，裁剪均包含对应配方标题/序号、材料、
  数量和工艺区域；重复材料词导致的跨区命中已在 `0e900b7` 收紧。
- 第 2 页 2 条配方：第 1 条因局部定位冲突使用较大安全区域，第 2 条使用较小区域；
  两者均可看到日期、材料和数量，用户始终可以打开整图。
- 裁剪只服务人工对照，没有写回或改变任何 FinalResult 字段。

### 浏览器回归证据

本地新代码服务端口 8767，真实 Job 页只读检查结果：

| 视口 | 结果 |
|---|---|
| 1440×900 | 7 crop、7“查看整图”；`position: sticky`；卡片 `overflow: visible`；无横向滚动 |
| 卡片内滚动 900px | 当前证据 top 约 12px，且 evidence bottom 未越过 card bottom |
| 滚入下一卡片 | 上一证据退出；下一证据 top 约 12px 后开始 sticky |
| 800×900 | 单列、证据 `position: static`、无横向滚动 |
| 375×812 | 单列、无横向滚动、输入控件约 44px |
| 浏览器控制台 | 0 warning/error |

### 安全与私人数据边界

- 本机生成的 crop、manifest、原图、OCR、FinalResult 和私人数据库均在 ignored
  `data/` 层，没有进入 Git。
- 本轮没有输出或提交 API Key、Authorization、完整模型响应或私人绝对路径。
- hash 篡改测试证明证据接口返回 404，review view 自动回退整图。
- 真实页面检查没有提交表单、确认配方、写知识库或导出 Excel。

### 本轮仍未解除的 Gate

- 用户尚未逐条确认这 7 条真实配方，因此不伪造 READY、知识写回或正式 Excel。
- Knowledge OFF 仍未得到成功 FinalResult，OFF/ON 净提升仍不可计算。
- 只有 5 张独立个人样图，未达到 10–20 张真实样本 Gate。
- 私人 Windows 安装器升级闭环仍待后续验收。

结论：本轮解决了“整图难对照、sticky 失效、日期原文显示为空、历史排序无法使用”
四项审查体验问题，但未解除上述发布 Gate。PR #9 必须继续保持 Draft，禁止 Merge、
Tag 和 Release。

## 2026-07-27 最新整改与真实 Gate（本节覆盖下方较早结论）

### 独立审查意见的代码处置

- 已增加并通过 `test_knowledge_trace_matches_final_value`、
  `test_knowledge_trace_survives_reload`、`test_final_result_contains_all_trace`。
- 已增加并通过 amount/date/formula_no 的流水线保护测试；历史知识不能覆盖
  数量、日期、配方号、编号或单位。
- VLM 前的知识候选改为先确定唯一高分 customer/product 上下文，再检索
  material/process；无客户上下文时不向 Prompt 注入材料或工艺历史。
- 已增加跨客户隔离回归；客户 B 不会收到只属于客户 A 的材料候选。
- Qwen3.7 Plus 使用 `json_object`、`enable_thinking=false` 和 SSE 流式接收；
  其他 OpenAI 兼容模型维持原请求路径。
- 官方阿里云 `*.aliyuncs.com` 的 qwen3.7-plus 使用紧凑业务 JSON 合同，
  返回后由本地代码补齐 record-v1，再执行原 Schema、Fusion、FinalResult 和
  Ready Gate；没有降低或绕过 Schema。
- 紧凑合同保留 source image、客户、产品、日期、材料、原始数量、单位、工艺、
  注意事项和置信度；本地归一化支持同页多产品和多图来源。
- 紧凑合同仅按解析后的官方阿里云 hostname 启用；伪装域名和其他模型已有
  反向测试。

### 最新真实两图 Knowledge ON Gate

全部使用本机私密按量配置；Key、Authorization、完整模型响应、私人数据库和
原图均未进入 Git 或本报告。

| 项目 | 结果 |
|---|---|
| Job | `20260727-200139-4e9558` |
| 图片数 | 2 张不同的真实个人样图 |
| OCR | 21,906 ms；1 张缓存命中 |
| Vision | 81,939 ms；收到流式 content |
| JSON / structured_result | 成功；59,969 B |
| Schema | `VALID`；0 issue |
| 记录 | 2 页、7 条配方 |
| Fusion | 成功；`fusion/result.json` 生成 |
| FinalResult | 成功；`review/final_result.json` 生成 |
| Job 状态 | `REVIEW_REQUIRED` |
| knowledge_trace | 57 `KEEP_RAW`、114 `FORBIDDEN`；trace/final 不一致 0 |

### Prompt 语义复验

Job `20260727-200552-b00c4a` 使用同两图、同模型、Knowledge ON，只增加以下
已复现版面规则：配方序号只读数字、日期归属当前配方、横向材料/数量对齐、仅
明确“工艺”行进入工艺字段、数字符号逐字符保留。

- OCR 3,485 ms（2 张缓存命中）；Vision 80,552 ms。
- 收到 content，2 页 7 条配方，Schema `VALID`，Fusion 与 FinalResult 均生成。
- 第 2 页材料/工艺误分得到改善；但第 1 页日期仍缺失，配方号仍需人工确认。
- 本地 OCR 对第 1 页日期已有串行错误，因此不能声称数字/日期准确率 Gate 全过。

### Knowledge OFF 对照

Job `20260727-200756-d3d1ec` 使用同图、同代码、Knowledge OFF。单次请求在响应头
前远端断开，未收到 content，也未生成 structured_result/FinalResult。按既定
规则未重试、未继续增加超时。

因此当前只能证明 Knowledge ON 完整链可运行，不能计算可靠的 OFF/ON 净提升；
本次 ON 结果也没有发生 `AUTO_CORRECT`，所以不得宣称知识纠偏已经提高准确率。

### Excel Gate

真实 ON Job 正确进入 `REVIEW_REQUIRED`：100 个 `NEED_REVIEW`、21 个 `CONFLICT`
字段尚待用户核对。正式导出器只允许 READY 且无未确认字段的 FinalResult。
本次没有伪造用户确认，因此尚未生成正式 Excel；这项发布 Gate 仍阻塞。

### 最新自动化结果

- 项目 `.venv`：`453 passed, 5 deselected`。
- `python -m ruff check lite_app tests_lite scripts`：通过。
- `git diff --check`：通过。
- 全局 Python 因缺少开发依赖 `xlwt` 在收集阶段退出；改用项目规定的 `.venv`
  后全绿，该环境差异不计作代码失败。

### 最新决策

- PR #9：继续 **Draft**。
- 已解除：真实 Qwen Knowledge ON 无 structured_result/FinalResult 的阻塞。
- 仍阻塞：Knowledge OFF/ON 净提升、用户确认后的 READY/Excel、更多真实样图准确率、
  私人安装器升级闭环。
- Ready / Merge / Tag / Release：均不允许。

## 最新独立审查回填（2026-07-27，第二轮）

收到的独立审查文本仍标注旧 HEAD `32daacf0e33dbc3a0f0a7d960f5e8b10e1551bed`；
接收审查时核验的实际 PR HEAD 为
`931f82508315b095068ef1e100701f88039688b9`。以下结论按实际代码和真实产物
重新核对，而不是直接接受旧 HEAD 的描述。

| 审查项 | 处置 | 核验证据 |
|---|---|---|
| P0-1 用户确认 → READY → Excel → 知识写回未完成 | **接受 / 阻塞** | ON Job 已有 FinalResult，但问题字段尚未由用户逐条确认；禁止伪造确认 |
| P0-2 Knowledge OFF/ON 双成功未完成 | **接受 / 阻塞** | ON 成功；同图 OFF 在响应头前断开且未按规则重试 |
| P1-1 增加人工 AUTO_CORRECT 与数字禁改测试 | **代码已存在，无需重复实现** | `test_unique_contextual_history_correction_writes_reversible_trace` 以及 amount/date/formula_no 两层保护测试；知识测试集 19 passed |
| P1-1 真实 AUTO_CORRECT 覆盖不足 | **接受 / 残余风险** | 真实 ON 为 57 KEEP_RAW、114 FORBIDDEN、0 AUTO_CORRECT |
| P1-2 跨客户隔离 | **通过** | 先确定唯一 customer/product；无客户上下文不注入 material/process；跨客户回归通过 |
| P1-3 自动纠偏策略 | **通过设计与单测，真实纠偏仍待证明** | 唯一高分、margin、上下文、OCR/VLM 证据同时满足才 AUTO_CORRECT |
| P1-4 “完整业务 Prompt 在 1024 仍失败” | **旧证据已被部分推翻** | 紧凑合同后的两个两图 Knowledge ON Job 均生成 structured_result/Fusion/FinalResult；但日期、配方号准确率仍未通过 |
| P2-1 Excel Gate | **接受 / 阻塞** | 100 NEED_REVIEW、21 CONFLICT，正式导出器按产品规则拒绝非 READY Job |
| P2-2 10–20 张样本 | **接受 / 阻塞** | 当前独立个人样图只有 5 张，不以重复图片凑数 |
| Secret / 私人数据 | **通过** | tracked 与 working diff Secret 均为 0；私人 Job、原图、数据库、响应均未入 Git |

### 第二轮审查后的执行边界

1. 不再大改 Knowledge 架构。
2. 不自动确认真实业务字段；用户必须在证据优先页面核对每条配方。
3. 不重复同一失败的 OFF 请求、不继续增加超时；后续 OFF 对照必须有明确的受控变量。
4. 不用现有 5 张图片的重复副本冒充 10–20 张独立样本。
5. 在用户确认、正式 Excel、同图 OFF/ON 双成功和更多独立样本完成前，PR #9
   继续 Draft，禁止 Merge、Tag、Release。

## 审查发现处置

| 原审查项 | 当前处置 | 证据 |
|---|---|---|
| P0-1 Knowledge 未进入决策链 | 已完成代码接线，等待独立复核和真实 Gate | Prompt references → typed retrieval → correction policy → Fusion → FinalResult `knowledge_trace` |
| P0-2 真实个人版 Pipeline Gate 未完成 | **仍阻塞** | 真实业务请求在响应头前远端断开，未生成 structured_result/FinalResult/Excel |
| P1-1 数字/日期/编号保护 | 已补显式测试 | `test_history_cannot_override_amount/date/formula_number` |
| P1-2 AI ZIP 安全 | 现有实现及测试覆盖 | 路径、重复成员、符号链接、声明、SHA、JSONL均为 fail-closed |
| P1-3 旧 Excel 误导入 | 已补分类证明，空模板已有提取级测试 | 报价、报告、成分表、物性、标签、合同和空模板 |
| P1-4 升级保护 | 已补三文件 hash 不变证明 | `knowledge.sqlite3`、`settings.json`、`secrets.env` |
| P2-1 未知日期 | 接受为残余风险 | 日期不参与当前词项强匹配；仍需用户补全后确认历史顺序 |
| P2-2 实体覆盖 | 部分完成 | material/process 已进入检索与 Fusion；customer/product 用作上下文和 Prompt，尚未作为独立 FinalResult 融合字段 |
| P2-3 证据访问 | 已补攻击测试 | `../` 越界返回 409；SHA 篡改返回 409 |

## 本轮实现

- OCR 后、VLM 前生成最多 20 条类型化知识参考，只包含 customer/product/material/process。
- Prompt 明确知识只是参考，新名称必须保留，数量、日期、配方号、编号、单位禁止按历史修改。
- VLM 后按 customer + product 上下文检索 material/process 候选。
- 不再把历史候选直接塞进通用 FusionEngine；先融合 OCR/VLM，再执行安全知识策略。
- 只有唯一高分、分差足够、上下文一致且存在 OCR/VLM 证据时才 `AUTO_CORRECT`。
- `SUGGEST` 强制进入人工复核；`FORBIDDEN` 保持原值。
- Fusion 与 FinalResult 保存 `original_value/history_candidate/final_value/decision/score/margin/reasons`。
- 增加 `KNOWLEDGE_ASSIST_ENABLED=false/true`，用于同代码、同图 OFF/ON Gate；Job 记录实际开关。
- 阿里云 qwen3.7-plus 大图发送前限制长边 1024、JPEG quality 70；其他模型不变。该变更仅通过极简真实请求验证，完整链仍阻塞，因此不得宣称修复完成。

## 自动化 Gate

- `python -m pytest -m "not real_ocr" -q`：**441 passed, 5 deselected**。
- `python -m ruff check lite_app tests_lite scripts`：通过。
- `git diff --check`：通过。
- tracked Secret 扫描：无匹配。
- working diff Secret 扫描：无匹配。

## 真实 Qwen3.7 Plus 受控 A/B/C

全部使用按量 `sk-ws` 私密配置层；Key、Authorization、完整业务响应均未进入 Git 或本报告。

| Case | 图片/Prompt | 请求体 | 结果 |
|---|---|---:|---|
| A | 探针图 2,203 B + 极简 Prompt | 3,396 B | HTTP 200；3,416 ms；收到 JSON content；marker 正确；request_id `c307010f-d200-90b9-a252-eddb46133e3a` |
| B | 同一真实图 200,590 B + 极简 Prompt | 267,877 B | 180,455 ms；无响应头/content；`RemoteProtocolError` |
| B2 | 同图缩到 576×1024、51,675 B + 极简 Prompt | 69,321 B | HTTP 200；7,962 ms；收到可解析 JSON；request_id `ffc61033-5ef9-9914-9616-2d3d184e1586` |
| B3 | 同图缩到 900×1600、126,222 B + 极简 Prompt | 168,717 B | HTTP 200；9,291 ms；收到可解析 JSON；request_id `72e74ff6-0973-93d1-b50e-95d7dbb167c4` |
| C | 1920×1080、226,113 B + 完整业务 Prompt | 323,409 B | OCR 32,274 ms；OCR 后至失败约 156,412 ms；无响应头/content；`RemoteProtocolError` |
| C-1600 | 1600 长边 + 完整业务 Prompt | 未保存业务体 | 约 107 秒后无响应头/content；`RemoteProtocolError` |
| C-1024 | 1024 长边 + 完整业务 Prompt | 未保存业务体 | OCR 2,977 ms；总计约 124 秒；无 structured_result；`RemoteProtocolError` |
| D | 1024 长边 + 精简业务合同 | 89,323 B | 16,623 ms；无响应头；`ConnectError`；按规则未重试，结论不确定 |

### 可支持的结论

- qwen3.7-plus 连接、视觉和 JSON 基础能力真实可用。
- 原尺寸真实图与完整业务请求都可能在响应头前断开；不是客户端 300 秒超时。
- 同图缩放后极简视觉请求可稳定成功，证明图片载荷/分辨率会影响结果。
- 完整业务 Prompt 在 1600 和 1024 两档仍失败，因此不能声称仅缩图已修复完整链。
- D 遇到不同的连接错误且未重试，不能据此判断精简业务合同是否有效。

## 仍然阻塞的发布 Gate

- Knowledge OFF/ON 尚未得到两份成功 FinalResult，无法计算净提升和新增错误。
- 当前仅有 5 张独立个人样图，未达到审查建议的 10–20 张。
- 真实多卡任务尚未生成 `vision/structured_result.json`。
- 尚未完成 Schema → Fusion → FinalResult → 用户确认 → 知识写回 → Excel。
- 未验证私人安装器升级后的完整个人版闭环。

## 当前决策

- PR #9：保持 **Draft**。
- Ready：不允许。
- Merge：不允许。
- Tag：不允许。
- Release：不允许。

## 2026-07-27 第三轮独立审查整改（以本节为准）

### 可直接复制给独立 GPT 的代码复核提示词

```text
请独立审查 daily-record-ocr-lite PR #9 的最新实际 Diff，重点审查提交
887b60374d6d28bd87f83de44d00996cbdfb6027，并与其父提交
132e0b63bd9675f47d58d116e357d6cd079af1ff 比较。不要只复述本报告。

请重点验证：
1. 配方证据是否使用与 OCR/VLM 预处理完全相同的 EXIF 和手动/自动旋转；
2. 页面内跨产品穿插的配方是否保留独立 source_order，且不会被分组顺序覆盖；
3. 模型 bbox 的页面顺序颠倒或高度重叠是否整组失效并安全回退；
4. 本地 Layout 是否真实参与定位，粗粒度单一 record 是否不会覆盖多配方安全分区；
5. evidence manifest 是否绑定 recognition_run_id、formula_id、source_order、source image、
   确定性 crop/full 文件名及 source/crop/full SHA-256；交换条目或旧批次是否 fail-closed；
6. 新识别批次开始时是否先使旧 manifest 失效；证据生成失败后是否仍不会暴露旧证据；
7. 通用 /jobs/{job}/files 路由是否禁止绕过专用 API 读取 manifest、crop 和旋转整图；
8. SQLite v4 的 ALTER、日期回填和 migration version 是否位于同一 savepoint，故障能否完整回滚；
9. 非空但不可解析日期是否明确进入待确认；窄屏按钮/输入是否至少约 44px；
10. 是否仍保持整图 OCR/VLM，裁剪只服务人工核对，不改变 FinalResult。

请输出 P0/P1/P2、Secret/私人数据边界、测试缺口、是否允许 PR #9 转 Ready、
是否允许 Merge。当前真实产品 Gate 仍未完成 OFF/ON 双成功、用户确认后的 READY/Excel、
10～20 张独立样本，因此禁止给出 Merge/Tag/Release 许可。
```

### 本轮代码范围

- 审查反馈基线：`132e0b63bd9675f47d58d116e357d6cd079af1ff`
- 整改实现提交：`887b60374d6d28bd87f83de44d00996cbdfb6027`
- PR：<https://github.com/liumingyang-maker/daily-record-ocr-lite/pull/9>
- PR 状态：Draft；本轮未合并、未打 Tag、未发布。

### 独立审查发现处置

| 发现 | 处置 | 代码/测试证据 |
|---|---|---|
| P0：裁剪坐标未复用识别旋转 | **已修复** | `orient_image()` 成为预处理与证据共用实现；不对称图片 90cw 回归验证方向和像素区域 |
| P1：跨产品分组覆盖页面来源顺序 | **已修复** | record-v1 新增可选 `source_order`；归一化前保存页面顺序；知识历史与裁剪使用该顺序；A1/B1/A2 回归为 1/2/3 |
| P1：页面 bbox 乱序/高重叠未校验 | **已修复** | 页面级顺序与 70% 高重叠检测；异常候选失效后走本地/安全区域 |
| P1：`layout_by_page` 被忽略 | **已修复** | Layout record/line 进入本地定位；record 数与配方数不一致时拒绝粗记录；短数字和带圈序号不再误命中数量行 |
| P1：manifest 可交换、未绑定当前批次 | **已修复** | schema v2 绑定 run/formula/source order/page/source path、确定性 crop/full 路径及三类 SHA；交换条目返回 None/404 |
| P1：重识别失败后可能继续展示旧证据 | **已修复** | 每次生成新 `recognition_run_id` 后、预处理前原子写入空 manifest；失败时旧批次不可达 |
| P1：通用文件路由绕过专用证据校验 | **已修复** | 通用路由拒绝 `review/evidence_regions.json` 和 `review/evidence/`；专用 API 才能返回校验后的 crop/full |
| P1：SQLite v4 缺少显式回滚边界 | **已修复** | `SAVEPOINT knowledge_v4`；第二行日期回填注入失败后列、数据和 version 均恢复 |
| P2：窄屏按钮不足 44px | **已修复** | 900px 以下 review 按钮 `min-height: 44px`；375px 实测约 43.998px（像素取整） |
| P2：逐配方重复哈希读取 | **已修复** | review view 单次请求共享路径哈希缓存；专用单图请求仍逐项 fail-closed |
| 审计旧段落覆盖度表述过强 | **已纠正** | 本节只声明已有代码/自动化/页面证据；产品发布 Gate 继续明确阻塞 |

### 自动化 Gate

| Gate | 结果 |
|---|---|
| 非真实全量测试 | **491 passed, 5 deselected** |
| Ruff | `python -m ruff check lite_app tests_lite scripts` 通过 |
| Diff check | `git diff --check` 通过 |
| tracked Secret scan | 0 match |
| working diff Secret scan | 0 match |

新增回归覆盖旋转方向、页面 bbox 乱序/重叠、Layout 定位与粗记录回退、重复数字锚点、
manifest 条目交换、当前批次绑定、旧证据失效、通用路由绕过、跨产品来源顺序、迁移故障回滚、
不可解析日期待确认和移动端触控尺寸。

### 真实 2 图 / 7 配方页面复核（不重新调用模型）

使用已有成功 Job `20260727-200552-b00c4a` 的持久化 OCR、Layout、FinalResult 和原图，
只重建 ignored `data/` 下的审查证据；未改写 FinalResult、未确认字段、未写知识库、未导出 Excel：

- manifest schema v2；run ID 与 Job/FinalResult 一致；7/7 配方有证据项；2 张旋转后整图均有 SHA 绑定；
- 第 1 页 5 条配方使用独立安全区域；短数字和带圈序号不会因数量行重复而扩张成整页；
- 第 2 页局部定位不够可靠时保留较大安全区域，符合“静默回退较大区域/整图”的产品决定；
- 1440×900：7 crop、7 个“查看整图”，当前卡片证据 `position: sticky`，滚动后 top 约 12px；
- 375×812：单列、`position: static`、无横向溢出，输入和按钮约 44px；
- 7 张证据图全部加载；浏览器控制台 0 error；通用文件路由绕过由 API 测试验证为 404。

### 仍然阻塞的产品 Gate

- Knowledge OFF/ON 尚未得到同图两份成功 FinalResult，不能计算净提升或新增错误；
- 真实样本中尚无 `AUTO_CORRECT`，不能声称知识纠偏已经提高真实准确率；
- 用户尚未逐条核对并确认真实配方，未进入 READY、未完成知识写回和正式 Excel；
- 当前只有 5 张独立个人样图，未达到 10～20 张真实样本 Gate；
- 私人 Windows 安装器升级闭环仍待后续验收。

结论：本轮修复了独立审查提出的证据正确性、安全绑定、顺序和迁移回滚问题，
但没有解除产品发布 Gate。PR #9 必须继续保持 Draft；禁止 Merge、Tag、Release。
