# 阶段接口

`POST /api/stages/<stage>` 接收 `multipart/form-data`。字段 `sample=dirty`、`sample=clean` 或 `file=<CSV>` 三选一。阶段为 `intake`、`prepare`、`calculate`、`policy`、`balance`。预览不入库。

`POST /api/runs` 接收同样的输入，执行全批并返回运行报告。`GET /api/runs` 返回最近 50 批。`GET /api/runs/<id>` 查询一批和当前复核状态。

`PATCH /api/runs/<id>` 接收 `revision`、`status` 和 `note`。状态使用 `APPROVED` 或 `HELD`。冲突返回 409，客户端读取新版本后重试。

`GET /api/runs/<id>/evidence` 下载内含运行清单、行号隔离、业务证据、待补清单和复核信息的 JSON。

运行报告中的 `supplement` 是待补清单：来源不全的业务组整体列在这里，不进入 `cases`。每项含 `case`、`status`（`SOURCE_INCOMPLETE`）、`records`（该组全部原始记录键）、`rejected_records`、`accepted_records`、`lines`、`reasons`、`detail` 与 `withheld_discount_cents`。`balance.released` 列出本批可签发的完整组，`balance.withheld` 列出本批待补组；两者互不影响。
