# Bot 选择与 Key 权限

管理员可绑定多个微信或飞书 Bot。每把 Key 单独关联允许调用的 Bot 与默认 Bot，会话和回复共用。

- 先调用 `getCallerIdentity`，从 `bots` 读取已授权 Bot 的 ID、名称、平台与状态。使用 `bot_id` 明确选择；不猜 ID、不绕过授权。
- 不指定 Bot 时使用 Key 的 `default_bot_id`；未设默认且只有一个授权 Bot 时可使用它。多个候选必须明确选择，不随机选、不广播。
- `channel` 仅是可选平台过滤条件，不能代替飞书 A / B 等同平台多个 Bot 的 ID。

微信使用摘要、手机页交互及各 Bot 独立的上下文、计数和空闲心跳。飞书使用原生卡片，无微信的十条估算或续期心跳。未配置或停用时说明状态，不擅自换 Bot。

`sendMessage`、`sendNotification`、`sendTaskCard` 和 `getDeliveryStatus` 都支持 `bot_id`。保存返回的 Bot ID、会话、去重键与原参数；重试和查回执保持一致，即使默认 Bot 后来改变也不改投其他 Bot。

`getMessages` 按本聊天会话与游标读取已授权 Bot 的回复，`bot_id` 标明连接，`source` 标明微信、飞书或网页。回信沿用入站 Bot ID。飞书单聊可带标签或引用原通知回复；无明确归属的消息留在公共收件箱。

飞书卡片提交后返回同样的 `task_response` 和唤醒事件。答复是用户输入，不表示已执行，也不绕过宿主权限。`updateTaskCard` 更新共享状态，并尝试同步飞书卡片；`card_delivery` 只说明更新接口结果，状态持久化后不要重新执行任务。

第一阶段支持本人单聊文字及五种任务卡片，飞书群聊、图片/文件收件和多租户尚未接入。
