# daily-record-ocr-lite 证据优先产品工作流审计报告

审计日期：2026-07-27  
审计分支：`feat/evidence-first-product-workflow`  
基线：`origin/master` / `8d5f3b2`  
已审计实现 SHA：`332309987203d72e77fc5b1d2954d9a32ba4735f`  
审计结论：**Phase 1 Web 与数据工作流达到 Draft PR 条件；未授权合并、Tag 或 Release。**

## 1. 审计范围

本次审计覆盖：

- 面向普通用户的全站语言与导航；
- 多图片顺序、删除和逐图旋转；
- 证据优先的整条配方确认工作台；
- 客户、产品、日期、配方、材料、数量、单位、工艺和备注的增删改排序；
- 用户确认、内容哈希、FinalResult、知识库写入回执、READY 和 Excel 的数据血缘；
- 同一客户和产品按日期追加的知识历史、详情、双版本比较和 Excel 导出；
- 设置页、五步首次配置页和脱敏诊断；
- v1 知识库到 v2 的非破坏迁移、备份与回滚边界；
- Windows/macOS 安装包的 Phase 2 设计规范。

本次明确不包含：

- Qwen 真实视觉业务请求重跑；
- OCR 性能、多核、Mac 适配或 Pipeline 重构；
- Windows/macOS 安装包产物构建、签名、公证；
- 合并、Tag 或 Release。

## 2. 需求与证据矩阵

| 用户目标 | 实现证据 | 自动化证据 |
|---|---|---|
| 默认只展示冲突、空值和低可信字段 | `review_view.py` 问题优先排序与折叠视图 | `test_review_view.py`、`test_user_workflow_e2e.py` |
| 原图证据与识别结果并排 | 配方卡片引用原图与证据框；窄屏降为单列 | `test_review_api.py`、浏览器桌面/390px 验收 |
| 用户只看业务字段 | 主界面不展示 Field ID、VLM、BBox、Provider/Model | `test_user_pages.py`、浏览器 DOM 验收 |
| 允许编辑、增加、删除和排序 | FinalResult 版本化编辑器和撤销 | `test_review_editor.py`、`test_review_api.py` |
| 一次确认整条配方 | 内容哈希确认；修改后自动失效 | `test_review_state.py`、`test_user_workflow_e2e.py` |
| 缺少日期时明确待确认对象 | 卡片显示客户/产品/配方和缺失日期原因 | `test_review_view.py`、浏览器验收 |
| 确认后进入知识库 | 只有有效确认哈希可生成知识写入回执 | `test_knowledge_history.py`、`test_readiness.py` |
| 同客户+产品按日期追加，不覆盖 | 追加式 transaction 与唯一内容指纹 | `test_knowledge_history.py`、E2E 重复提交验收 |
| 历史可浏览、比较和导出 | 客户/产品/日期时间线、双版本差异、Excel | `test_knowledge_pages.py`、`test_knowledge_exporter.py`、浏览器交互验收 |
| FinalResult 是正式 Excel 数据源 | READY/导出要求确认与知识回执；导出读取正式结果 | `test_exporter.py`、`test_readiness.py`、E2E |
| 设置和安装面向用户 | 基础项前置，高级项折叠，五步首次配置 | `test_user_pages.py`、浏览器验收 |

## 3. 数据血缘与状态 Gate

正式链路为：

`图片证据 → OCR/Vision → FinalResult → 用户整条确认哈希 → 知识库追加回执 → READY/REVIEW_REQUIRED → Excel`

审计确认：

1. 配方编辑直接更新版本化 canonical FinalResult，不另造旁路数据源；
2. 用户确认保存当前规范化内容的哈希；后续编辑会令旧确认失效；
3. 知识库只接收确认仍有效、日期完整的配方；
4. 知识写入生成可核验回执，READY 和 Excel Gate 均检查该回执；
5. 重复提交使用内容指纹保持幂等，不会重复追加；
6. 相同客户和产品的新日期记录为追加，不删除或替换历史。

## 4. 迁移与回滚

- v1 数据库升级到 v2 前先创建备份；
- 迁移只增加知识历史结构，不覆盖用户原记录；
- 测试覆盖旧库升级、备份存在、重复执行和现有数据保留；
- 本次没有读取或改写桌面正式运行目录中的用户数据库、Job、配置或密钥。

## 5. 自动化 Gate

执行环境：Windows，Python 3.11.15，PaddlePaddle 3.3.1 CPU，PaddleOCR 3.7.0。

| Gate | 结果 |
|---|---|
| `python -m pytest -m "not real_ocr" -q` | **317 passed, 5 deselected** |
| `python -m pytest -m real_ocr -q -s` | **5 passed, 317 deselected** |
| PP-OCRv6 真实推理 | **通过，1875ms，tokens=3** |
| `python -m ruff check .` | **All checks passed** |
| `git diff --check` | **通过** |
| Doctor | **SETUP_REQUIRED；全部 critical checks PASS** |

Doctor 的非关键提示只有：隔离工作树未配置私人视觉服务，以及本机 8765 端口已被另一运行实例占用。OCR provider load、FinalResult schema、Excel export、数据目录和核心依赖均 PASS，因此不是 `BROKEN`。

## 6. 浏览器验收

使用独立临时 Job 和知识数据库启动本地应用，未连接用户正式 `data/`：

- 任务确认页显示“第 4 步：确认与导出”，不再显示裸数字 `4`；
- 一页两条配方时，有问题配方优先展开，已完整配方默认折叠；
- 原图证据、材料、数量、单位、工艺、备注和整条确认操作可见；
- 知识库展示“联创 / G30A / 两个日期”，选择两条后成功显示数量与工艺变化；
- 识别记录页只展示客户、产品/牌号、日期、状态、图片数、创建时间和下一步；
- 设置页只要求普通用户先填写模型和 API Key，高级设置默认折叠；
- 首次配置页按“环境、AI 配置、AI 测试、OCR 测试、开始使用”五步呈现；
- 任务页、知识库、设置和安装引导在 390px 窄屏下均无横向溢出；
- 应用页面控制台错误数：**0**。

## 7. Secret 与私有产物审计

执行结果：

- `git grep -n -E 'sk-(ws|sp)-[A-Za-z0-9._-]+'`：**0 matches**；
- 当前 diff 同规则扫描：**0 matches**；
- Git 工作区中没有提交 `data/settings.json`、`data/secrets.env`、`data/setup_health.json`、`data/jobs/`、测试日志、SQLite 数据库、用户图片、原始 AI 响应或 Excel；
- Doctor 生成的本机缓存、知识数据库和健康文件均由 `.gitignore` 排除；
- 没有删除用户本机配置文件。

## 8. 代码审计要点

- 用户页面和内部诊断字段分层，内部标识只保留在折叠的高级诊断中；
- 编辑 API 使用 optimistic version 防止旧页面静默覆盖新修改；
- 原始证据只作引用，不在确认过程中覆盖旧 Job；
- 知识库写入采用事务和内容指纹，防止部分写入和重复历史；
- 导出 Gate 与 readiness Gate 共用确认/回执事实，不允许只改页面状态绕过；
- 旧 `/jobs/{id}/result` 地址保留兼容重定向到统一确认工作台。

## 9. 已知限制与下一阶段

1. 本 UX 分支没有使用或复制用户的 Qwen Key，也没有重跑真实视觉调用；Qwen3.7 P0 修复不属于本次变更。
2. Windows/macOS 安装包目前只有已批准设计文档 `2026-07-27-desktop-installers-design.md`，实际打包、签名和 macOS 公证属于 Phase 2 独立 PR。
3. macOS 公证不等于必须上架 App Store；它是 Apple 对站外分发应用的开发者签名与恶意软件检查流程。
4. 当前只满足创建 Draft PR 的条件；在 Phase 2 资产 Gate 和独立审核完成前，不应声称安装包已交付。

## 10. 最终审计结论

**建议：允许将 Phase 1 作为 Draft PR 提交进一步审核。**

理由：核心业务链路已经由单元、集成、双图 E2E、真实 OCR 和浏览器验收共同覆盖；FinalResult、用户确认、知识历史、READY 与 Excel 之间建立了可追溯 Gate；Secret 和用户私有数据未进入 Git。

**禁止事项：本报告不授权合并、不授权 Tag、不授权 Release，也不代表 Phase 2 桌面安装包已经完成。**
