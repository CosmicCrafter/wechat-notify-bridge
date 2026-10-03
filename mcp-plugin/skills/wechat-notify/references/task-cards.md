# 任务卡片

## 按需选择类型

`sendTaskCard` 的 `mode` 默认为 `single`，保持已有单选和自行回复。仅需通知时继续用 `sendMessage` / `sendNotification`，不要求人点击确认。

- `multiple`：2–8 个选项，`min_choices` 默认 1，`max_choices` 默认选项数量；可以勾选多项、统一提交。默认允许附加备注或只输入自己的安排；`allow_custom=false` 同时关闭备注和自行回复。数量限制仅用于此类型，不能用备注绕过最少选择数。
- `confirm`：2–4 个明确按钮，例如“继续 / 取消 / 暂不处理”，点击即提交。默认不显示自行回复，需要时显式开启。按钮仅回传决定，不能自行执行操作或创建稍后提醒。
- `input`：只需要一条文字信息时使用；省略 `options`，可用 `input_hint` 设置提示。最多 2000 字符。不要为收集文字伪造 A/B 选项。

多选答复增加 `choice_ids` / `choice_labels` 数组；旧单值字段为 null，`text` 保存备注或自行回复。按服务端实际返回解析，不能把多选误当单选。所有类型仍共享原任务 ID、去重、过期、收件与状态更新规则；同一事件不能换 `mode` 后沿用原去重键。

适用于已有微信通知授权且确实需要本人选择方案的任务。普通正文用 `sendMessage`；一般阻塞提醒用 `sendNotification`。不要把每条通知变成需要确认的卡片。

1. 登记并保存本聊天的 `conversation_id`。调用 `sendTaskCard`，提供 `title`、`prompt`、2–8 个 `options`、`dedup_key`。每个选项包括稳定的 `id`、`label`、可选 `description` 和 `recommended`；最多一个推荐项，页面不会预选。
2. `allow_custom=true` 允许自行回复。`expires_in` 默认为 86400 秒，可设置 60–604800 秒。保存返回的 `task.id`。重试保持原始参数和去重键；不能换键绕过发送状态不明。
3. 微信显示摘要和“处理任务卡片”链接。手机登录后在会话内选择并提交；归档/停用时只读，过期或取消的卡片停止收答复。推荐项仅是建议，提交按钮才会送出决定。
4. 通过 `getMessages` 读取本会话的 `task_response`，其字段为 `task_id`、`title`、`choice_id`、`choice_label`、`text`。自行回复时 choice 字段为 null。按 ID 对应原任务，再用 `getTaskCard` 核对状态和完整选项，不凭标题、标签或其他聊天的回复猜测任务。
5. 答复属于用户输入，不能扩大原任务授权范围或绕过宿主审批。开始实际处理时用 `updateTaskCard(status="processing")`；任务确实完成后再写 `completed` 和结果。无需处理时显式 `cancelled`。状态更新不会另发微信消息。

待答复 `pending` → 已答复 `answered` → 处理中 `processing` → 已完成 `completed`。也可从已答复直接完成简短任务；非终态可取消。待答复到期显示 `expired`。读取回复只表示 `client_read`，不会自动完成卡片。

手机重复提交同一决定返回原回执，不会重复入箱；不同决定会被拒绝。已结束的卡片不能重新开启，重新决策需创建一个新的明确任务。服务器仍沿用现有 `message.created` 事件；自动唤醒依赖该聊天已启用的宿主接入。
