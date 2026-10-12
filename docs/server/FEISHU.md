# 飞书双向通道

服务器 1.15.0 与插件 1.9.0 开始支持可选飞书应用机器人。与微信共用客户端密钥、会话、历史、任务状态和唤醒事件；不需要绑定微信，也不会改变微信上下文、推送计数或心跳。普通程序可直接调用相同 HTTP API。

第一阶段使用现有 HTTPS 服务接收飞书事件与卡片回调。飞书默认关闭，无额外接收进程，不增加 SDK 或前端框架。现有 Key 默认关联原微信 Bot，旧调用保持兼容。每个 Bot 绑定一个本人收件身份，当前不开放群聊、多租户和飞书图片/文件收件；长连接接收可在通道边界内后续加入。

## 配置应用

1. 在[飞书开发者后台](https://open.feishu.cn/app)创建企业自建应用，启用机器人能力。群自定义 Webhook 机器人不具备本项目需要的原生卡片回传能力。
2. 申请以应用身份发消息 `im:message:send_as_bot`、读取用户发给机器人的单聊消息 `im:message.p2p_msg:readonly`，设置应用可用范围包含本人并发布。
3. 在通知桥 Admin 的“Bot 管理”添加飞书 Bot，点“配置 Bot”，填写 App ID、App Secret、本人 Open ID、Verification Token 和 Encrypt Key，勾选启用。Open ID 在该应用上下文中获取，不能使用其他应用的 Open ID。
4. 事件配置与回调配置都选择“发送至开发者服务器”，填写管理页为这个 Bot 显示的同一个地址：`https://你的域名/wechat/channels/feishu/<bot_id>/callback`。两处配置与 Admin 使用相同 Verification Token / Encrypt Key；接收端只接受加密并通过签名校验的事件。
5. 订阅消息事件 `im.message.receive_v1` 和卡片回调 `card.action.trigger`，发布新版本，使权限与订阅生效。
6. 给机器人发送带有会话标签的消息，或引用发出的通知回复，确认 AI 的收件箱出现 `source="feishu"`。有宿主接收器或事件订阅时会沿现有机制唤醒；安装插件本身不会启用唤醒。

App Secret 和回调密钥加密存入已有 SQLite 数据库，不写进源码、插件、镜像或普通日志，也不回显给页面和 AI。空白密码字段保留原值；应用与配对用户身份固定，Secret 和回调密钥可以轮换。停用飞书保留历史，微信继续正常运行。备份规则与原服务一致：数据库和加密主密钥一起备份。

## 调用

在 Admin 为程序或 AI 创建独立客户端密钥，关联允许使用的 Bot，登记当前聊天并保存 `conversation_id`。同一客户端可以授权微信、飞书 A、飞书 B 等多个 Bot，每次明确选择一个 Bot。

```json
{
  "bot_id": "该飞书Bot的ID",
  "conversation_id": "已登记的会话ID",
  "dedup_key": "system-error-unique-event",
  "text": "**运行异常**\n\n数据同步失败，请检查任务日志。"
}
```

在“Key 授权”勾选此 Bot，然后向 `/api/messages` POST 上面的 JSON，带 `Authorization: Bearer <客户端密钥>`。`/api/notifications`、`/api/task-cards` 与 MCP 发送工具同样接受 `bot_id`，详见[多 Bot 规则](BOTS.md)。

回执查询 `/api/deliveries` 或 `getDeliveryStatus` 要带原 `bot_id`、会话和事件键。不同 Bot 的同名事件键独立；发送结果不明时不得切换 Bot 或换键重发。超时保留未知状态，重复请求只返回原记录。`api_accepted` 仅表示飞书接口接受，不表示本人已查看或手机已收件。

## 回复与任务卡片

普通回复可在飞书引用该会话的通知，自动按上游消息 ID 关联；也可以用 `[客户端-会话] 正文`。不能明确路由的消息进入公共收件箱，不自动唤醒某个 AI。只接收配置的本人单聊，忽略其他用户、群聊及机器人消息。

卡片采用飞书 JSON 2.0，复用已有单选、多选、快捷确认、独立输入和轻量表单定义。回调按配对用户、原消息、任务和会话联合校验，在本地事务中提交；相同答案重复回调只产生一条收件与唤醒事件，冲突答案、过期任务和归档会话均不可提交。答案进入统一 `getMessages`，返回 `task_response`；提交表示已答复，后续执行由调用方决定。

`updateTaskCard` 更新共享任务状态并尝试更新原飞书卡片，返回 `card_delivery`；更新失败不回滚已保存的任务状态，也不自动重新执行任务。手机会话页提交仍使用同一任务状态，旧飞书卡片再点击会重新校验。

机器人支持 `/help`、`/status`、`/list` 与 `/web`。`/web` 返回一次性登录码用于完整会话页；密钥生命周期仍由 Admin 管理。指令重投不重新生成登录码，回复正文暂时加密排队，发送尝试后清除，旧指令不执行。

## 验证与边界

模拟上游与真实加密签名的 HTTP 测试覆盖发送、独立去重、凭据隔离、本人过滤、引用路由、统一唤醒事件和五种卡片。测试不等于飞书实机验收：部署后还须验证实际消息到达、卡片渲染、提交回调和对应宿主唤醒。

协议参考：[发送消息](https://open.feishu.cn/document/server-docs/im-v1/message/create)、[接收消息](https://open.feishu.cn/document/server-docs/im-v1/message/events/receive)、[卡片回调](https://open.feishu.cn/document/feishu-cards/card-callback-communication)、[表单容器](https://open.feishu.cn/document/feishu-cards/card-components/containers/form-container)。加密和签名实现对照飞书[官方 Python SDK](https://github.com/larksuite/oapi-sdk-python/tree/5a3c9779bc013258203fcadab2660a1b276feb34/lark_oapi)。
