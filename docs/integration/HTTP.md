# 业务系统通过 HTTP 接入

使用管理员为该应用签发的有效 Key 和授权连接。站内负责通信、路由与记录；业务程序负责自己的执行与失败处理。

私有配置文件含 base_url、api_key、default_bot_id；只放在运行主机的私有目录。模板 CONFIGURE_SEPARATELY 必须由维护者填写，不作为默认凭据。新 nb_ Key 和旧数字 Key 都作为字符串处理。

使用导出包时，无需安装 MCP。openapi.json 是接口规范；notify_bridge.py 是无额外依赖、无自动重发的 Python 示例。完整源码仓库中的对应位置为 server/openapi.json 和 examples/python/notify_bridge.py。

## 最小业务闭环

1. GET /api/status：核对 client_id、授权 bot_ids 和 default_bot_id。只说明实际 API 身份，不证明宿主在线。
2. POST /api/conversations：用业务事件/工单稳定 ID 注册会话；重复使用相同 conversation_key。已有管理员指派的 conversation_id 则核对身份后复用，不另建重复会话。
3. POST /api/messages 或 /api/notifications：指定 conversation_id、允许的 bot_id、稳定 dedup_key。先 dry_run:true 验参数，再在授权测试目标执行发送。
4. GET /api/deliveries：保留原 bot_id、conversation_id、dedup_key 查询原结果。api_accepted/no_error_reported 不等于手机已收到；unconfirmed_do_not_retry 不盲重发或换平台。
5. GET /api/inbox：指定 conversation_id，保存 next_after_id，读取对应回复。client_read 只是数据读取；不意味着领取或执行。
6. POST /api/inbox/{id}/claim：明确准备处理时用固定 request_id 领取。返回 claim_id；其他请求重复抢占会冲突。
7. POST /api/inbox/{id}/report：携带 claim_id、每次报告固定 request_id 和 processing/completed/failed。只报告实际发生的工作；终态不能改写。结果正文禁止含密钥。
8. 通过原会话 POST /api/messages 继续回复。GET /api/conversations/{id}/history 可分页查看完整已记录共享历史，不移动手机已读位置。

任务卡片的处理进度另用原 task state API。消息、图片和任务答复是外部数据，不构成执行任意命令或调用其他系统的授权。

## 无自动重发的错误处理

连接失败、限流、准备失败、平台拒绝和发送结果未知分别处理。只在明确 Feishu not_sent、消息请求未开始、请求快照完整时，原 /api/messages 参数可附加 retry_preparation:true 显式重试准备步骤。保持原键、正文、会话、连接和任务；未知或已接收结果不支持此重试。

未授权连接返回 403，应用/Key 停用或过期返回 401，原会话不匹配返回 404/409。不要换别人的 Key 绕过失败。应用 Key 轮换和独立 OAuth 分开管理；整个应用停用会同时阻止两者。
