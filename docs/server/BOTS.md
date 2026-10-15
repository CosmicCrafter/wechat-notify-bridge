# 多 Bot 管理与 Key 授权

第一版由一个管理员管理多个微信或飞书 Bot，对外发放程序 / AI 调用 Key。平台是传输类型，Bot 是具体连接，应用是稳定调用身份，Key 是它的凭据。同一接口通过 `bot_id` 选择 Bot，不自动广播或切换渠道。

## 管理流程

1. 在 Admin 的 **通信连接** 输入名称，选择微信或飞书，添加连接。
2. 微信 Bot 使用独立二维码绑定，接收进度、上下文、推送计数和空闲心跳分别保存。飞书 Bot 配置独立应用凭据和本人 Open ID，按[飞书说明](FEISHU.md)订阅回调。
3. 在 **接入应用** 创建调用方，勾选允许使用的 Bot，可设置一个默认 Bot。原始 Key 仅在创建或轮换时显示，服务器长期只保存哈希。
4. 既有 Key 点击 **Bot 权限** 修改授权和默认 Bot。撤销某个 Bot 不轮换整个 Key，也不会自动获得其他 Bot 权限。
5. Bot 支持改名和启停；停用保留绑定、历史和回执，阻止新调用并暂停微信后台收发。可确认后删除连接，保留历史；删除前核对受影响应用。最后一个管理员恢复连接受保护，不能以停用或删除绕过恢复约束。

当前最多登记 32 个 Bot；同一微信上游绑定或飞书应用不能重复挂到不同 Bot。重绑保留原账号或应用，新增账号或应用应新建 Bot。

## 统一接口

先 `GET /api/status` 或调用 MCP `getCallerIdentity` 获取当前 Key 的 `bots` 与 `default_bot_id`。只返回已授权的 Bot，不猜 ID。

```json
{
  "bot_id": "管理页或身份接口返回的BotID",
  "conversation_id": "当前聊天登记的会话ID",
  "dedup_key": "monitor-error-unique-event",
  "text": "**任务异常**\n\n数据同步失败，请检查日志。"
}
```

向 `/api/messages` POST，带 `Authorization: Bearer <Key>`。`/api/notifications`、`/api/task-cards` 与 MCP 发送工具使用相同的 Bot 参数。

省略 Bot 时使用 Key 的默认 Bot；未设默认且只有一个授权 Bot 时使用它；多个候选则返回 `bot_required`，不会随机选择。可选 `channel` 是平台过滤条件，与显式 Bot 平台冲突会被拒绝。未授权、停用或不存在的 Bot 无法调用。

保存返回的 **bot_id、conversation_id、dedup_key 和原参数**。查 `/api/deliveries` 或 MCP `getDeliveryStatus` 要带原 Bot，即使管理员之后改变默认 Bot也不应改投。各 Bot 去重独立，但发送结果未知时不允许通过换 Bot 绕过去重。

## 回复与权限

回复通过 Bot 与会话关联，统一进入 `getMessages`，携带 `bot_id` 和 `source`。AI 回信优先使用原 Bot。不同 Bot 的同名上游消息 ID 不会互相吞掉；同一 Bot 的重投只记录一次。

只有该 Key 获准的 Bot 的回复可读取并触发唤醒事件。新 UI 归档只改变列表可见性，不停止收发；停用应用或撤销 Bot 授权仍影响后续路由。本人登录手机会话页可以查看全部历史；网页回复属于当前会话，不刷新任何微信 Bot 的上下文。

会话、任务状态和宿主绑定继续共用。飞书卡片按原 Bot、消息、任务和本人共同校验，不能串用另一 Bot 的回调。

## 升级兼容

原微信连接保留为 `bot_id="default"`。原 Key 仅保留该 Bot 的权限和默认选择，绑定、历史、去重记录和 OAuth 不轮换；新增 Bot 不自动授权给旧 Key。原请求省略新参数仍沿原微信连接工作。

Bot 凭据在共用 SQLite 中加密保存，和会话、客户端、权限一起备份；数据库和主密钥必须一起备份。微信运行状态采用独立命名空间。服务仍需单实例、单 worker，保留 Docker / Python 部署，不引入微服务、队列或平台 SDK。
