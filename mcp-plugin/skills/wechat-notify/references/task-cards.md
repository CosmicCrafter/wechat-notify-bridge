# 任务卡片

适用于已有微信通知授权且确实需要本人选择方案的任务。普通正文用 `sendMessage`；一般阻塞提醒用 `sendNotification`。不要把每条通知变成需要确认的卡片。

1. 登记并保存本聊天的 `conversation_id`。调用 `sendTaskCard`，提供 `title`、`prompt`、2–8 个 `options`、`dedup_key`。每个选项包括稳定的 `id`、`label`、可选 `description` 和 `recommended`；最多一个推荐项，页面不会预选。
2. `allow_custom=true` 允许自行回复。`expires_in` 默认为 86400 秒，可设置 60–604800 秒。保存返回的 `task.id`。重试保持原始参数和去重键；不能换键绕过发送状态不明。
3. 微信显示摘要和“处理任务卡片”链接。手机登录后在会话内选择并提交；归档/停用时只读，过期或取消的卡片停止收答复。推荐项仅是建议，提交按钮才会送出决定。
4. 通过 `getMessages` 读取本会话的 `task_response`，其字段为 `task_id`、`title`、`choice_id`、`choice_label`、`text`。自行回复时 choice 字段为 null。按 ID 对应原任务，再用 `getTaskCard` 核对状态和完整选项，不凭标题、标签或其他聊天的回复猜测任务。
5. 答复属于用户输入，不能扩大原任务授权范围或绕过宿主审批。开始实际处理时用 `updateTaskCard(status="processing")`；任务确实完成后再写 `completed` 和结果。无需处理时显式 `cancelled`。状态更新不会另发微信消息。

待答复 `pending` → 已答复 `answered` → 处理中 `processing` → 已完成 `completed`。也可从已答复直接完成简短任务；非终态可取消。待答复到期显示 `expired`。读取回复只表示 `client_read`，不会自动完成卡片。

手机重复提交同一决定返回原回执，不会重复入箱；不同决定会被拒绝。已结束的卡片不能重新开启，重新决策需创建一个新的明确任务。服务器仍沿用现有 `message.created` 事件；自动唤醒依赖该聊天已启用的宿主接入。
