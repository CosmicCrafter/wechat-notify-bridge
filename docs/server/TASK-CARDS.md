# 可交互任务卡片

## 按需选择，保持简单

服务端 1.12.0、插件 1.7.0 起，在同一个 `sendTaskCard` 工具中按需指定 `mode`。无需启用全部类型，省略时仍是原有单选。只需要通知时继续用 `sendMessage` / `sendNotification`，不用创建卡片。

| 需要 | mode | 参数与交互 |
| --- | --- | --- |
| 通知即可 | 无需卡片 | 普通发送工具，不要求用户作答 |
| 从方案里选一个 | `single`（默认） | 2–8 个选项；原有单选和自行回复 |
| 一次选几个项目 | `multiple` | 2–8 个选项；`min_choices` 默认 1，`max_choices` 默认选项数；勾选后统一提交 |
| 快速表明决定 | `confirm` | 2–4 个按钮，点击即提交；默认关闭自行回复 |
| 补充一条信息 | `input` | 不传选项；直接填写文本后提交，`input_hint` 可设置占位提示 |

这些类型共用发送、去重、收件箱、过期和状态更新机制，不增加工具、数据库表、定时器或唤醒轮询。手机端只在加载含任务卡片的记录时下载交互 JS/CSS；普通会话不下载。完成、取消、过期的卡片不参与额外的任务状态轮询。原单选卡片的去重指纹保持兼容。

在下文通用参数的基础上，可以按需使用以下片段：

```json
{"mode":"multiple","min_choices":1,"max_choices":2,"options":[{"id":"fix","label":"修复问题"},{"id":"test","label":"补充测试"},{"id":"docs","label":"更新文档"}]}
```

多选默认允许附加备注，也可以不选任何项目、只填写自己的安排。选择了项目时，数量必须符合限制；备注不能绕过最少选择数。`allow_custom=false` 同时关闭备注和自行回复。同一组选项的提交顺序不同仍视为同一决定；多选答复在 `task_response` 中增加 `choice_ids` 和 `choice_labels` 数组，旧的两个单值字段为 null。

```json
{"mode":"confirm","options":[{"id":"continue","label":"继续"},{"id":"cancel","label":"取消"},{"id":"hold","label":"暂不处理"}]}
```

快捷按钮仅回传所选决定，具体执行由原会话的 AI 按已有授权处理。不会自动创建稍后提醒。需要自行回复时可显式设置 `allow_custom=true`。点击前没有默认选择；结果不明时冻结原决定，重试保持同一请求与答复。

```json
{"mode":"input","input_hint":"例如：微信通知桥"}
```

独立输入仅收集一条非空文本，最多 2000 字符，不需要伪造 A/B 选项。字段只应用于对应类型：选择数量限制仅用于多选，`input_hint` 仅用于独立输入。完整表单、日期、提醒调度不在本次范围内。

服务端 1.11.0、MCP 插件 1.6.0 起支持单选和自定义回复。微信发送问题摘要及“处理任务卡片”链接；按钮位于登录后的手机会话页。发送卡片不会替代普通通知，也不会新建唤醒后台。

## 从 AI 发起

先用 `registerConversation` 保存当前聊天的 `conversation_id`，再调用 `sendTaskCard`：

```json
{
  "conversation_id": "已有登记返回的32位ID",
  "dedup_key": "deployment-plan-20261003",
  "title": "选择部署方式",
  "prompt": "两种方案都可行，请选择适合你的方式。",
  "options": [
    {"id": "docker", "label": "Docker 部署", "description": "配置统一，后续升级方便。", "recommended": true},
    {"id": "python", "label": "直接运行 Python", "description": "适合已有 Python 环境的服务器。"}
  ],
  "allow_custom": true,
  "expires_in": 86400
}
```

示例 ID 必须替换为本聊天实际登记返回的 ID。每个选项有稳定、互不重复的 ID，2–8 个选项，最多一个推荐项。推荐项不会预选。`expires_in` 范围为 60 秒至 7 天，默认 24 小时。`dry_run=true` 仅校验发送准备情况，不创建卡片、不发微信。

返回原有发送回执和 `task` 对象；保存 `task.id`、会话 ID、去重键及完整原始参数。发送结果不明时先用原参数查询 `getDeliveryStatus`，不能换键盲目重发。重复创建返回同一张卡片，不延长有效期。微信接口接受不等于手机确认收件。

## 手机端处理

选择一个方案，或者选择“自行回复”并填写安排，点击“提交决定”。卡片显示“已答复”，普通会话记录同时保存你的回答。两个设备同时提交时只有一个不同决定能成功；同一决定的重试返回原回执，不重复入箱。关闭页面前保留未提交草稿的提示，草稿仅在当前页面内存中保存。

归档或停用的会话保留卡片并只读；过期、取消的卡片停止接收决定。删除会话同时清理卡片定义、答复和处理结果。卡片正文、决定、结果使用原有服务端主密钥加密保存。链接不包含令牌，也不授予免登录访问。

## AI 接收并更新

用本聊天的 `getMessages` 读取答复，消息中包含可读正文及：

```json
{
  "task_response": {
    "task_id": "实际卡片ID",
    "title": "选择部署方式",
    "choice_id": "docker",
    "choice_label": "Docker 部署",
    "text": ""
  }
}
```

自行回复时 `choice_id`、`choice_label` 为 null。按任务 ID 对应原问题，再调用 `getTaskCard` 核对；不要仅凭标题匹配。答复进入原聊天的普通收件箱，沿用现有 `message.created` 事件和桌面接收器。因此，已经为该聊天启用的唤醒接入可以继续使用；仅安装 MCP 不会自动唤醒宿主。

状态为 `pending` → `answered` → `processing` → `completed`；简短任务可从已答复直接完成。非终态可以 `cancelled`，待答复超过期限显示 `expired`。客户端读取只更新消息的已读状态，不自动开始或完成任务。实际开始处理后调用 `updateTaskCard(status="processing")`；实际完成后调用 `completed` 并提供 `result`。状态更新在手机会话页刷新显示，不另发微信。

重复更新相同状态和结果是幂等的；终态不可重开，同一状态下改写结果会拒绝。用户的决定不扩大原任务授权，也不替代宿主要求的审批。

## HTTP API

- 客户端创建：`POST /api/task-cards`，Bearer 调用密钥，字段同 MCP 示例。
- 客户端查询：`GET /api/conversations/{conversation_id}/tasks/{task_id}`。
- 客户端更新：`POST /api/conversations/{conversation_id}/tasks/{task_id}/state`，传 `status` 和可选 `result`。
- 手机提交：`POST /chat/api/conversations/{conversation_id}/tasks/{task_id}/answer`，使用手机登录 Cookie、同源 Origin 和 `X-Chat-Request: 1`，传 `request_id`、`choice_id`、`text`。

调用密钥只访问自身会话；手机登录不能当作客户端密钥使用。网页提交不会更新微信回复上下文或顺延空闲心跳。
