# 业务系统通过 HTTP 接入

使用管理员为该应用签发的有效 Key 和授权连接。站内负责通信、路由与记录；业务程序负责自己的执行与失败处理。

私有配置文件含 base_url、api_key、default_bot_id；只放在运行主机的私有目录。模板 CONFIGURE_SEPARATELY 必须由维护者填写，不作为默认凭据。新 nb_ Key 和旧数字 Key 都作为字符串处理。RELEASE.json 的 fingerprint_scope=onboarding-template 标明网站共享模板来源，不能与 developer-docs 文档包直接比较指纹，也不覆盖导出后加入的私有凭据。

使用导出包时，无需安装 MCP。openapi.json 是接口规范；notify_bridge.py 是无额外依赖、无自动重发的 Python 示例。完整源码仓库中的对应位置为 server/openapi.json 和 examples/python/notify_bridge.py。

## 从下载包直接运行

在 notify-bridge-http 目录打开终端（完整文档包则在仓库/文档包根目录执行，脚本路径为 examples/python/notify_bridge.py）。Python 3.12+，无需额外依赖。先由获授权维护者配置 `.private/client.json`，不要把 Key 写在命令参数、终端历史或 AI 对话中。

```sh
python notify_bridge.py --config .private/client.json --identity-only
python notify_bridge.py --config .private/client.json --conversation-key system-job-001 --event-id job-001-notice
```

第一条只核对应用身份与授权，不登记会话、不发消息；第二条登记稳定会话并执行 dry_run，尚未投递。确认独立目标和通知授权后，在第二条命令后加 `--send` 才真实发送。重复同一业务事件保持会话键、事件键和正文不变；不要为了重试改键。程序不会自动重发或启动长期轮询。

已有 NOTIFY_BASE_URL / NOTIFY_API_KEY / NOTIFY_BOT_ID / NOTIFY_CONVERSATION_KEY / NOTIFY_EVENT_ID 环境变量方式保持可用；指定 --config 时整组地址和凭据来自该文件，避免混用两套身份。配置错误仅显示固定错误，不打印文件内容。

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

## F02 受保护会话

同一应用 Key 可创建多个会话。POST /api/conversations 增加 receiver_mode:protected 和 host_type:http，首次返回 receiver_setup；业务程序立即将其安全存到仅本进程可访问的私有配置，禁止记录响应正文。随后以 X-Notify-Receiver 提交 receiver_token，并 POST /api/receivers/verify 提交 challenge，验证后删除本地挑战。管理员创建则用私有配对文件 POST /api/receivers/exchange 获得 setup 再验证；同一注册键重试不重新签发秘密，丢失时由管理员换绑。

后续读/发/history/task/claim/report 均带原应用认证与会话接收头。示例 NotifyBridge 构造可传 receiver_token；claim 返回 generation，report 用 generation=原值，lease 到期前 renew。不能把共享 Key 当作已验证 AI 聊天身份。详细说明见[会话接收协议](RECEIVERS.md)。

应用策略/会话偏好由管理员配置；未指定目标才允许路由，level=urgent 需授权并受间隔限制。显式目标不会覆盖。查询原策略请求回执时，bot_id/channel 仍省略，不因返回实际 B 而改变请求。muted 代表消息保存但没有普通平台发送；平台接收不等于鸣响或业务完成。
