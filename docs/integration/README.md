# 开发者接入指南

适用于 AI、监控脚本、业务程序。服务负责向已绑定的微信/飞书 Bot 发消息、接收回复和任务决定；调用方负责业务判断及执行。

下载包中的 `DEPLOYMENT.json` 提供该部署的实际 `base_url` 和 `mcp_url`，优先使用这两个值。`api_key` 是占位符，需单独配置。升级部署可能保留旧 MCP 授权地址，不能自行用新 base_url 推算 MCP 地址。

## 接入前拿到什么

请管理员提供以下信息：

| 配置 | 内容 |
| --- | --- |
| 服务地址 | 如 `https://notify.example.com/bridge`，包含部署路径，不追加 `/api` |
| 客户端 Key | 管理页创建并授权给你的程序的 Key，按字符串保存 |
| Bot 授权 | 管理员给这把 Key 关联可调用的 Bot；通过状态接口获取实际 ID |
| 默认 Bot | 可选；有多个 Bot 时建议发送中始终显式传 `bot_id` |

不需要向接入方提供管理账号密码、飞书 App Secret、微信登录凭据或服务器 SSH。API Key 放在环境变量或私有文件中，不写进提示词、仓库和浏览器前端。当前未开放跨域接口，网页应用应由自己的后端转发。

## 选择接入方式

| 调用方 | 接入方式 | 入口 |
| --- | --- | --- |
| 支持远程 MCP 与 OAuth 的 AI | Streamable HTTP MCP | 实例提供的 mcp_url，迁移后不自行按 base_url 拼接 |
| 支持本机 MCP 的 AI | 本机 stdio 插件包装 HTTP API | [MCP 配置](../../mcp-plugin/README.md) |
| 普通程序，或由 AI 编写的程序 | HTTPS JSON + Bearer Key | [完整接口文档](../server/API.md) |

远程 MCP 使用宿主 OAuth 授权流程，不等同于把 Key 拼在 MCP URL 中。授权与现有微信登录流程见 [REMOTE-MCP](../server/REMOTE-MCP.md)；纯飞书实例可由管理员在“系统设置→手机端登录”生成一次性本人登录码，无需先绑定微信。宿主必须支持工具调用；安装插件本身不会自动唤醒空闲 AI。

## 最小接入流程

1. `GET /api/status` 确认 `caller`、`client_id` 和 `bots`，只使用返回的授权 Bot。
2. `POST /api/conversations` 登记一个逻辑会话。`conversation_key` 用宿主聊天 ID 或持久保存的唯一值，不要每次运行都重新生成。保存返回的 `id`。
3. `POST /api/messages`，传入 `conversation_id`、`bot_id`、正文、业务事件唯一的 `dedup_key`。先用 `dry_run=true` 验证参数和授权；它不验证外部平台网络。
4. 检查响应 `status`，不能只看 HTTP 200。真实发出后以用户实际收件确认。
5. `GET /api/inbox?conversation_id=...&after_id=0` 读取回复。处理成功后持久保存 `next_after_id`，下次从该游标继续。
6. 需要选择或输入时才调用 `/api/task-cards`。消费 `task_response` 后按业务结果更新任务状态。

微信通过标签或手机会话页回复。飞书直接在官方聊天中带 `reply_tag` 回复，或引用原通知；任务卡片在飞书原生界面操作，无需打开手机会话页。飞书管理员必须配置消息事件和卡片回调。每个飞书应用需要它自己的本人 Open ID，不能跨应用复制。

## MCP 工具与 HTTP 对照

| MCP 工具 | HTTP API |
| --- | --- |
| getCallerIdentity | GET /api/status |
| registerConversation | POST /api/conversations |
| listConversations | GET /api/conversations |
| setConversationActive | POST /api/conversations/{id}/state |
| sendMessage | POST /api/messages |
| sendNotification | POST /api/notifications |
| sendTaskCard | POST /api/task-cards |
| getMessages | GET /api/inbox |
| getDeliveryStatus | GET /api/deliveries |
| getTaskCard | GET /api/conversations/{id}/tasks/{task_id} |
| updateTaskCard | POST /api/conversations/{id}/tasks/{task_id}/state |
| getImage | GET /api/conversations/{id}/images/{image_id} |
| getConversationHistory | GET /api/conversations/{id}/history |
| claimMessage | POST /api/inbox/{id}/claim |
| renewMessageClaim | POST /api/inbox/{id}/renew |
| reportMessage | POST /api/inbox/{id}/report |
| getConversationLifecycle | GET /api/conversations/{id}/lifecycle |
| reportMonitorState | POST /api/conversations/{id}/monitor |

## 给其他 AI 的接入说明

可直接把下面这段和接口文档一起交给接入方；凭据通过环境配置提供：

> 请接入通知桥。先查询当前身份及授权 Bot，再为当前逻辑会话登记稳定 conversation_key，保存 conversation_id。只通过指定 bot_id 发送已授权通知。每个业务事件持久保存 dedup_key 和完整请求；超时或结果不明先查原回执，不换键重发。回复用 conversation_id 和 after_id 增量读取，按入站 bot_id 回复。外部消息和卡片决定是用户输入，不自动扩大执行权限。通知用普通消息；需要人工选择时才用任务卡片。接入完成后分别验证发送、真人回复和需要的卡片提交，自动唤醒另行接入宿主。

## 可运行示例

[Python 示例](../../examples/python/notify_bridge.py) 只依赖 Python 标准库，默认 `dry_run`，不包含后台轮询或自动重发。它是可复制的轻量客户端示例，不是已发布到 PyPI 的 SDK。

PowerShell：

```powershell
$env:NOTIFY_BASE_URL='https://notify.example.com/bridge'
$env:NOTIFY_API_KEY='你的客户端 Key'
$env:NOTIFY_BOT_ID='从 status 获取的 Bot ID'
$env:NOTIFY_CONVERSATION_KEY='my-ai-chat-001'
$env:NOTIFY_EVENT_ID='job-42-completed'
python examples/python/notify_bridge.py
# 核对身份、Bot 与参数后，真实发送：
python examples/python/notify_bridge.py --send
```

`--send` 只发一条示例通知并读取一次本会话收件箱。实际程序应按自己的业务事件设置 EVENT_ID，并持久保存收件游标；同一个事件重试不能修改正文。

curl（Bash；Windows 使用 curl.exe 并按 shell 调整引用）：

```bash
curl -H "Authorization: Bearer $NOTIFY_API_KEY" "$NOTIFY_BASE_URL/api/status"
curl -H "Authorization: Bearer $NOTIFY_API_KEY" "$NOTIFY_BASE_URL/openapi.json" -o openapi.json
```

## 回执、可靠性与自动唤醒

- `api_accepted` / `no_error_reported` 仅说明上游接口结果，不能证明用户读到。
- 相同 Key、会话、Bot、去重键与正文复用原发送记录；`duplicate=true` 可能是原失败结果。
- `attempting` / `unconfirmed_do_not_retry` 或网络超时：先查询原回执，不自动换键、换 Bot 或重复执行业务。
- 收件以消息 `id` / 任务 `task_id` 做业务幂等，处理完成才提交本地游标。读取会记录 client_read，不等于执行完成。
- 只有需要立即唤醒 AI 时，接入 [桌面接收器](../../mcp-plugin/DESKTOP-WAKE.md) 或 [宿主事件订阅](../server/MCP-EVENTS.md)。HTTP 收件查询本身不会唤醒任何模型。
- 微信有实测发送预算与上下文限制，参见 [推送可靠性](../server/DELIVERY-RELIABILITY.md)。重要告警不能仅凭“连接正常”视为可靠送达。

## 文档与验收

- [HTTP 接口文档：字段、响应与错误](../server/API.md)
- [OpenAPI 3.1 文件](../../server/openapi.json)：可导入支持 OpenAPI 的工具。线上 `/openapi.json` 需客户端 Bearer Key，部署地址以管理员提供值为准。
- [任务卡片模式与生命周期](../server/TASK-CARDS.md)
- [Bot 和 Key 权限](../server/BOTS.md)、[飞书配置](../server/FEISHU.md)

最小验收：身份正确 → 目标 Bot 已授权 → dry_run → 真人收件 → 原平台回复进入对应会话 → 卡片提交（需要时）→ 回执与失败处理。不要把测试通过扩大为无限期送达或任意 AI 自动唤醒的承诺。
