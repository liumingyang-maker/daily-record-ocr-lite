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

请输出 P0/P1/P2、Secret/私人数据边界、是否允许 Ready、是否允许 Merge。
真实 Knowledge ON 已生成 structured_result 和 FinalResult，但 OFF 对照失败，
且用户尚未确认问题字段、未生成正式 Excel；禁止给出允许发布结论。
```

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
