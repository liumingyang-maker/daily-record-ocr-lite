# Qwen3.7 Plus record-v1 Schema Prompt 修复设计

## 背景

真实 Job `20260725-151256-8a9956` 已证明 Qwen3.7 Plus 能返回纯 JSON，
但结果在 `record-v1` 校验阶段产生 95 个致命错误。模型返回了业务内容，失败点不再是
连接或 JSON 解析，而是输出契约不一致。

当前 `pipeline_v2` 只向模型发送简化 instructions、OCR、Layout，以及一句“符合
JSON Schema”，没有发送 `record-v1` Schema 本体。阿里云 Qwen3.7 Plus 请求又按兼容
策略使用 `response_format={"type":"json_object"}`，因此 API 只保证 JSON 对象，
不保证符合本地 Schema。

## 目标

让正式 Vision 请求明确获得完整 `record-v1` 输出契约，使模型能够生成可进入 Schema、
Fusion、FinalResult 和 Excel 阶段的结果。

成功标准：

1. Qwen3.7 Plus 请求仍使用 `json_object`、`enable_thinking=false` 和至少 300 秒
   timeout。
2. 正式业务 Prompt 包含压缩后的完整 JSON Schema。
3. Prompt 明确 `source_image_index` 从 1 开始，bbox 使用 `[0,1]` 归一化坐标。
4. 自动化测试先失败后通过，并覆盖 Prompt 契约和 Qwen 请求参数。
5. 使用同图新建真实 Job，不覆盖旧失败 Job。
6. 真实 Job 必须收到 content、生成 structured result、通过致命 Schema Gate、
   生成 FinalResult，并成功导出 Excel，才能建议把 PR #4 转为 Ready。

## 方案

在 `pipeline_v2` 提取一个纯函数构建 Vision user prompt。输入为：

- schema config；
- OCR evidence；
- Layout evidence。

输出 Prompt 依次包含：

1. 现有业务 instructions；
2. 压缩 JSON 形式的完整 `record-v1` Schema；
3. 1-based 页面索引和归一化 bbox 的明确提醒；
4. OCR 与 Layout 辅助证据；
5. 只返回 JSON 对象的要求。

Schema 使用紧凑 JSON 序列化，避免缩进产生不必要的请求体膨胀。Schema 只作为 Prompt
内容发送，不切换到严格 `json_schema` response format。

## 数据流

```text
record_schema.yaml + record-v1.schema.json
                  │
OCR evidence + Layout evidence
                  │
                  ▼
       build_vision_user_prompt()
                  │
                  ▼
OpenAICompatibleVisionProvider
  json_object + thinking=false
                  │
                  ▼
JSON提取 → record-v1校验 → Fusion → FinalResult → Excel
```

## 错误处理

- 不通过正则或映射表篡改模型业务字段。
- 不把像素 bbox 静默转换成看似正确的归一化值。
- 不把错误状态值改成合法枚举。
- Schema 不合规时继续由现有 Gate 阻止 Fusion 和导出。
- 旧失败 Job、原始响应和本机私密配置保持不变且不进入 Git。

## 测试策略

先新增失败测试，证明当前 `pipeline_v2` Prompt 缺少：

- `schema_version` 等顶层契约；
- material / formula 等嵌套必填字段；
- review status 枚举；
- bbox 的 `0..1` 范围；
- 1-based `source_image_index` 提示。

实现后验证：

1. 目标 Prompt 测试；
2. Qwen 请求体参数测试；
3. 全量非 `real_ocr` 测试；
4. Ruff 和 `git diff --check`；
5. Secret 扫描；
6. 同图真实 Job 与 Excel Gate。

## 非目标

- 不修改 OCR、Layout、Fusion、FinalResult 或 Excel 逻辑。
- 不增加自动重试、并发、预热、Mac 适配或性能优化。
- 不启用严格 `json_schema` API 格式。
- 不合并 PR、不创建 Tag 或 Release，除非真实完整 Gate 通过。
