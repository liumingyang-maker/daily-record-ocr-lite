# 数据与隐私

上传图片、识别中间件、复核记录和 Excel 位于本机 `data/jobs/`。跨任务缓存位于
`data/cache/`，知识库位于 `data/knowledge.sqlite3`。视觉模型配置决定图片是否会
发送到本机或第三方端点；用户应阅读该服务的隐私条款。

API Key 位于环境或 `data/secrets.env`，不写入公开设置、任务或日志。卸载默认保留
`data/`。清缓存须运行 `scripts/cache_admin.py clear --yes`；删除识别数据必须由
用户明确决定并先备份。
