# HTTP API 接口文档

首次接入先看 [开发者接入指南](../integration/README.md)。机器可读规范见 [OpenAPI 3.1](../../server/openapi.json)，线上以带客户端鉴权的 `GET /openapi.json` 为准。下述 JSON 示例均为示意数据，不含真实凭据。

假设公开地址为 `https://notify.example.com/bridge`，下表的路径都相对于该地址。真实地址由部署者配置。

1.15.0 起，发送与查回执接受 `bot_id`，按当前 Key 的授权列表路由。`GET /api/status` 返回允许的 Bot 和默认 Bot；原 Key 仍默认使用原微信连接。完整规则见 [多 Bot 与 Key 授权](BOTS.md)。`channel` 是可选平台过滤条件，不能代替多个同平台 Bot 的明确选择。

下表除 `/health` 外的消息 API 需要 `Authorization: Bearer <API_KEY>`。收件人由服务器绑定确定，请求不能指定其他收件人。网页管理使用独立管理员密钥，不能用消息 API 密钥代替。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | /health | 进程健康 |
| GET | /api/status | 调用身份、接收状态、最近活动、下次心跳 |
| POST | /api/messages | 发送 Markdown 消息 |
| POST | /api/notifications | 发送任务提醒 |
| GET | /api/deliveries?dedup_key=... | 查询发送记录 |
| GET | /api/inbox?after_id=0&limit=20 | 按游标读取微信、飞书及网页回复 |
| GET | /openapi.json | 当前配置对应的 OpenAPI |

## 普通消息

```json
{
  "text": "实验完成了。",
  "dedup_key": "experiment-42-complete",
  "dry_run": true
}
```

`dry_run: true` 只校验，不发微信；省略或设为 false 才实际发送。服务端根据密钥给正文加上 `[客户端名称]`。API 正文最多 20000 字符；微信展示内容（含标记和会话链接）最多 2000 字符，超出时发送短摘录。去重键最多 200 字符，不接受空白内容。调用方不能用 source 或 caller 参数覆盖身份。

## 任务提醒

```json
{
  "task": "实验结果检查",
  "reason": "出现两个可选方案，需要确认下一步。",
  "need_user": "请选择方案 A 或 B。",
  "dedup_key": "experiment-42-decision-1",
  "level": "warning",
  "dry_run": true
}
```

必填 task、reason、need_user、dedup_key；level、dry_run 可选。level 为 info、warning 或 urgent。旧 `source` 字段继续接受以兼容旧插件，但不参与身份识别或消息来源标记。

## 去重与结果

同一客户端内，相同 dedup_key 和正文不会重复提交；同键不同正文返回 HTTP 409。不同客户端使用独立去重空间，查询发送记录也仅查本客户端。客户端改名或重置密钥不改变其稳定 ID，保留去重记录；旧版导入的客户端仍可查询原来的对应发送记录。`server-heartbeat-` 和 `server-command-` 前缀由服务器保留。

HTTP 200 不等于发送成功：必须检查响应的 status，duplicate=true 也可能返回先前的失败结果。

| status | 含义 |
| --- | --- |
| dry_run_ready | 校验通过，未发送 |
| api_accepted | 目标平台接口明确接受 |
| no_error_reported | 微信接口未报告错误 |
| phone_confirmed | 导入的历史记录已有人确认收件 |
| api_rejected | 目标平台接口拒绝 |
| unconfirmed_do_not_retry | 结果未知，不自动重发 |
| attempting | 请求已登记，可能仍在执行或被中断 |
| not_found | 无对应发送记录 |

接口接受不等于手机已收到或用户已阅读。当前没有用于自动写入 phone_confirmed 的公开接口。

1.14.0 起，新发送回执包含 `diagnostics`：上下文时间/年龄、发送前的本地已接受计数、请求字符/UTF-8 字节数、上游 HTTP 状态与 `ret`/`errcode`、请求用时、固定错误分类和说明。上游任意错误文本不回显；旧回执为 `null`。`/api/status` 增加 `context_received_at`、`context_age_seconds`、`accepted_sends_since_context`、`quota_warning` 与 `last_send_diagnostics`；本地计数并非微信剩余额度。详见 [推送限制与诊断](DELIVERY-RELIABILITY.md)。

1.14.1 起微信展示内容附加本地剩余提示，例如 `(5/10)`；按发送前计数估算发送成功后剩余条数。它与消息链接一样属于展示层，不进入原正文、内容哈希或网页历史。归零前在微信 Bot 直接发普通消息即可刷新，无需 AI 标签；网页回复不刷新微信上下文。接口、认证与去重协议保持兼容。

HTTP 401 表示鉴权失败，422 表示参数错误，503 表示服务执行异常。结果不明时先查原 dedup_key，不要换键重发。

首次绑定前发送返回 409 / `wechat_not_bound`；已绑定但未收到首条微信消息时返回 409 / `waiting_for_first_wechat_message`。`/api/status` 增加 `bound`、`context_ready`、`connection_status`。未能开始心跳计时或微信会话已过期时，`next_heartbeat_at` 为 null。

`/api/status` 的 `caller` 为密钥对应的名称，`client_id` 为稳定客户端 ID。密钥停用或重置后旧密钥返回 HTTP 401，无需重启服务。查询状态会更新客户端“最近调用”时间，但不改变微信空闲心跳计时。

接收状态与发送结果独立。`last_send_status`、`last_send_error_code`、`last_send_at` 表示最近一次发送尝试；`send_recovery_hint` 提供恢复建议。发送回执的 `recovery_hint` 对应本次尝试。`connected` 仅表示接收连接正常，不保证发送或手机收件。错误码 `-2` 本身不能确认具体原因；可先直接在微信 ClawBot 发送一条新消息，再验证发送。网页回复不会更新微信上下文。服务不会自动重发失败或结果未确认的消息，也不会因新入站消息就宣称发送恢复。

## 读取回复

响应包含 `messages` 和 `next_after_id`。各客户端保存自己的 next_after_id，下次作为 after_id。读取不会删除消息，也不会重置心跳时间。

管理指令及密钥回复不会返回。传 conversation_id 时只读取该聊天的指定回复，必须属于当前密钥。不传时读取公共收件箱（未带标签、未知或含糊标签），不代表消息归属本聊天。include_unaddressed=true 可合并公共消息，每种读取范围单独维护游标。返回项含 conversation_id、route_status（direct/shared/unknown/ambiguous），有标签时含 routing_tag；匹配成功的正文去掉开头标签。

### 聊天登记与路由

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | /api/conversations | `{conversation_key, name?}` 幂等登记，返回 ID、名称和标签 |
| GET | /api/conversations | 本密钥下的聊天和 active_count，可加 include_closed=true |
| POST | /api/conversations/{id}/state | `{active: true/false}` 启用或结束聊天 |

conversation_key 为稳定宿主聊天 ID 或一次性生成后保存的唯一标识（1–128 位字母/数字/点/冒号/下划线/短横线）；name 为 1–20 位中英文、数字、下划线或短横线。重名追加编号，缺省分配数字；相同 conversation_key 返回原登记，不改名。/api/status 额外返回 conversation_count 和 conversations。

一个启用聊天时显示 `[客户端]`，多个时显示 `[客户端-聊天名]`；reply_tag 始终带聊天名。微信开头的 `[标签]` 按收取时的启用聊天表解析，含糊时不猜测。名称变化、停用后旧标签可能不再匹配，用微信 /chats 查看。消息、通知、回执接口可传 conversation_id，去重范围为客户端加聊天，标签变化不会重发同一事件。

多个聊天时，未提供 conversation_id 的发送返回 409 conversation_required，聊天已结束返回 409 conversation_closed，不属于本密钥返回 404。停用/删除客户端后不能发送，定向历史不会转入其他聊天或公共收件箱。同一密钥下的聊天不是额外鉴权边界。服务只收存路由，宿主主动读取，不自动唤醒。

服务器仅返回文本或语音转写文本及消息类型，不下载图片、视频或文件。返回的微信内容是外部输入，不能自动作为执行代码、审批或派发任务的授权。

可导入的静态接口描述见 [openapi.json](../../server/openapi.json)。其中域名是占位符，使用前替换；服务运行时的 `/openapi.json` 根据 WECHAT_PUBLIC_BASE_URL 生成实际地址。

## 管理页面与绑定接口

`GET /admin/` 及其 CSS/JS 为公开页面框架，不包含任何凭据、二维码或账号数据。根路径跳转到该页面。

以下操作必须带 `Authorization: Bearer <ADMIN_KEY>`，不属于 MCP 工具，也不进入供 AI 使用的 OpenAPI。服务器未配置管理员密钥时返回 503。

| 方法 | 路径 | 参数 / 用途 |
| --- | --- | --- |
| GET | /admin/api/status | 服务状态与扫码状态，不返回微信 token 或用户 ID |
| POST | /admin/api/pairing/start | JSON `{ "replace": false }`；已有绑定时需明确为 true |
| GET | /admin/api/pairing/qr?session_id=... | 受鉴权保护的 PNG，仅在二维码可用时返回 |
| POST | /admin/api/pairing/verify | JSON `{ "session_id": "...", "code": "手机显示的数字" }` |
| POST | /admin/api/pairing/cancel | JSON `{ "session_id": "..." }`；取消尚未确认的本次扫码 |

活动扫码会话重复 start 会复用已有会话。结束后两秒内重复 start 返回 429。验证码与取消请求必须匹配当前 session_id，旧页面不能操作后来的会话。管理页面用 Authorization 头请求二维码，再生成内存图片地址，不把管理员密钥放进 URL、本地存储或日志。所有响应禁止缓存，未开放跨域接口。

## 管理客户端

以下接口同样仅接受独立的 `ADMIN_KEY`；微信的同名操作作用于同一份客户端记录。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | /admin/api/clients | 返回客户端列表与 base_url；不返回密钥或哈希 |
| POST | /admin/api/clients | JSON `{ "name": "codex" }`；创建并返回一次 api_key |
| POST | /admin/api/clients/{id}/rename | JSON `{ "name": "开发助手" }`；保留密钥 |
| POST | /admin/api/clients/{id}/rotate | 重置并返回一次新 api_key，同时重新启用 |
| POST | /admin/api/clients/{id}/revoke | 停用，不返回原始密钥 |
| POST | /admin/api/clients/{id}/delete | 删除客户端及其密钥，历史消息保留，不返回原始密钥 |

创建/重置响应包含 `client`、字符串 `api_key`、`base_url`。名称重复返回 409，名称格式错误返回 422，ID 不存在返回 404。原始密钥只在这次响应中显示，响应丢失需重新重置；长期凭据表仅存 SHA-256 哈希。指令回复临时队列使用服务器主密钥加密，尝试发送后清除正文，结果未知不自动重发。

删除接口仅供管理员使用，响应为被删除客户端的公开 `client` 信息。删除后旧密钥返回 401，列表移除该客户端，重启也不会从旧配置恢复。尚未发送的该客户端密钥回复会作废并清除；已发送消息无法撤回。同名重新创建会获得新 ID 和新密钥，使用独立去重空间，不继承旧客户端的发送回执。


## 手机会话链接与全文（1.4.0）

`POST /api/messages` 的 `text` 接受最多 20000 字符。登记会话的出站正文加密保存，微信正文自动附加认证后的 `/chat/?c=<conversation_id>&m=<message_id>` 链接；2000 字符以内保留正文，超过微信长度预算时发送短摘录。链接不是访问凭证，不包含 API 密钥。未登记会话或未配置公开 URL 的长消息返回 422。

发送回执与查询回执增加 `message_id`、`conversation_url`。历史发送没有正文时两者可以为 null。dry_run 不创建历史，重复调用不创建第二条历史，失败发送也保留正文并明确标记微信提醒失败/未确认，不自动重发。

`GET /api/inbox` 同时包含对应聊天的网页回复（`source=web`），游标规则不变。服务在将消息返回给客户端时记录“客户端已读取”；这不代表模型已经处理或执行。网页回复不更新微信心跳或 context_token。参见 [CHAT.md](CHAT.md)。


## 完整客户端接口清单

所有 `/api/` 请求使用 `Authorization: Bearer <客户端 Key>`；JSON 请求带 `Content-Type: application/json`。以下均相对服务地址（例如 `/wechat`），不是相对域名根路径。管理接口不属于第三方接入合同。

| 方法 | 路径 | 请求与主要响应 |
| --- | --- | --- |
| GET | `/api/status` | 无请求体；返回 caller、client_id、bots、bot_ids、default_bot_id、conversations |
| GET | `/api/conversations` | query include_closed=false；返回 conversations、active_count |
| POST | `/api/conversations` | body conversation_key、name?；返回会话对象，使用其 id |
| POST | `/api/conversations/{id}/state` | body active；返回会话对象 |
| POST | `/api/messages` | 见下表；返回发送回执 |
| POST | `/api/notifications` | task、reason、need_user、dedup_key，加通用路由字段；返回发送回执 |
| POST | `/api/task-cards` | title、prompt、conversation_id、dedup_key、模式字段，加 bot_id；返回回执及 task（dry_run 不创建任务） |
| GET | `/api/deliveries` | query dedup_key 必填，conversation_id、bot_id、channel 可选；返回原发送回执或 not_found |
| GET | `/api/inbox` | query conversation_id、after_id=0、limit=20（1–100）、include_unaddressed=false；返回 messages、next_after_id、content_is_untrusted |
| GET | `/api/wake/events` | query conversation_id 必填、after_id?、limit=20（1–100）；返回 events 中的消息 id 与 next_after_id，不标记已读；省略 after_id 仅取当前末尾游标 |
| GET | `/api/conversations/{id}/tasks/{task_id}` | 返回 `{task: {...}}` |
| POST | `/api/conversations/{id}/tasks/{task_id}/state` | body status、result?；更新任务，可能返回 card_delivery |
| GET | `/api/conversations/{id}/images/{image_id}` | 返回图片元信息及 base64 data；不是二进制响应，详见 [IMAGES](IMAGES.md) |
| GET | `/openapi.json` | 返回 OpenAPI 3.1；需要客户端鉴权 |

### 发送消息字段

| 字段 | 类型 | 必填/默认 | 约束 |
| --- | --- | --- | --- |
| text | string | 必填 | 非空白，最多 20000 字符 |
| dedup_key | string | 必填 | 非空白，最多 200 字符；一次业务事件固定值 |
| conversation_id | string | 建议始终传 | 登记返回的会话 id；多个活跃会话时必须明确 |
| bot_id | string | 默认 Key 的默认 Bot | 从 status.bots 选择，1–64 位字母/数字/下划线/短横线 |
| channel | string/null | 可选 | wechat / feishu，只作平台过滤；不应代替 bot_id |
| dry_run | boolean | false | true 时不发送、不创建消息历史，不能验证上游送达 |

飞书使用原生卡片展示全文，不附加网页入口；仍受编码后卡片内容 28000 字节限制，超限返回拒绝回执。微信长度、摘要与上下文限制见上文。

```json
{
  "conversation_id": "0123456789abcdef0123456789abcdef",
  "bot_id": "feishu-default",
  "text": "备份任务已完成。",
  "dedup_key": "backup-20261012-completed",
  "dry_run": false
}
```

### 任务提醒字段

`task` 最多 200 字符，`reason` / `need_user` 各最多 800 字符，均非空白。`level` 默认 warning，可选 info / warning / urgent。`conversation_id`、`bot_id`、`channel`、`dedup_key`、`dry_run` 与普通消息一致。`source` 为兼容字段，不覆盖服务端身份。

### 会话、回执与收件示例

登记请求：

```json
{"conversation_key":"my-ai-chat-001","name":"开发助手"}
```

会话响应的关键字段（示意，可能包含其他字段）：

```json
{"id":"0123456789abcdef0123456789abcdef","name":"开发助手","active":true,"display_tag":"[my-ai]","reply_tag":"[my-ai-开发助手]"}
```

飞书发送回执示例：

```json
{"channel":"feishu","bot_id":"feishu-default","status":"api_accepted","duplicate":false,"attempted_at":1791797499.5,"error_code":null,"phone_delivery":"unconfirmed","diagnostics":{"http_status":200,"provider_message_id":"om_example","duration_ms":100},"message_id":100,"conversation_url":"https://notify.example.com/bridge/chat/?c=0123456789abcdef0123456789abcdef&m=100"}
```

`conversation_url` 是兼容的内部历史链接，飞书卡片不会展示它。时间戳采用 Unix 秒；调用方按自己的时区格式化。平台与历史版本间字段可能缺省或为 null；不要强制假设所有回执都有相同 diagnostics。

收件示例：

```json
{"messages":[{"id":64,"received_at":1791797554.9,"message_at":1791797554.1,"conversation_id":"0123456789abcdef0123456789abcdef","route_status":"direct","text":"收到","source":"feishu","bot_id":"feishu-default","item_types":[1],"attachments":[]}],"next_after_id":64,"content_is_untrusted":true}
```

历史微信消息可能没有 source/bot_id，不要因此丢弃。回复携带 `task_response` 时按其 task_id 关联原任务。图片消息可能没有文字。程序只消费自己的会话；公共收件箱须显式选择，不能把无归属回复当作任意任务的批准。

### 任务卡片字段与状态

必填 conversation_id（32 位十六进制）、dedup_key、title（1–120 字符）、prompt（1–4000 字符）。expires_in 默认 86400 秒，范围 60–604800。模式及字段完整约束见 [任务卡片接口](TASK-CARDS.md) 和 OpenAPI 的 TaskCard / CardField schemas。

| mode | 模式字段 |
| --- | --- |
| single | 2–8 个 options；allow_custom 默认 true |
| multiple | 2–8 个 options；min_choices 默认 1，max_choices 默认选项数 |
| confirm | 2–4 个 options；allow_custom 默认 false |
| input | 不传 options；allow_custom=true；可传 input_hint |
| form | 1–5 个 fields；不传 options，不允许 allow_custom=true |

```json
{"conversation_id":"0123456789abcdef0123456789abcdef","bot_id":"feishu-default","dedup_key":"release-42-confirm","title":"是否继续发布","prompt":"检查已完成，请选择。","mode":"confirm","options":[{"id":"continue","label":"继续"},{"id":"cancel","label":"取消"}]}
```

用户提交后由 pending 变成 answered。调用方可以将已答复任务更新为 processing，完成后更新为 completed，并附 result（最多 4000 字符）；取消用 cancelled。不要把尚未答复的任务标记为处理中/完成；终态不能重新打开。提交决定不意味着系统已执行，业务副作用由调用方控制。

### 错误处理表

HTTP 错误通常为 `{"detail":"错误标识"}`；422 参数校验也可能返回 detail 数组。不要依赖错误文本固定措辞。

| HTTP / 回执 | 处理 |
| --- | --- |
| 401 | Key 缺失、失效、被停用；检查客户端凭据，不改用管理员 Key |
| 403 bot_access_denied | Key 未获准调用该 Bot，请管理员授权 |
| 404 | Bot、会话或资源不存在/不可访问；不要猜测其他客户端资源 |
| 409 | 如 conversation_required、conversation_closed、bot_disabled、去重冲突；按具体 detail 修正配置或请求 |
| 422 | 字段、枚举、卡片组合不合法；检查 OpenAPI 和模式规则 |
| 429 | 限流或数量限制；停止高频调用，按实际限制恢复 |
| 503 / 网络超时 | 发送可能已经执行；使用原 Bot、会话、dedup_key 查询回执 |
| HTTP 200 + api_rejected | 平台拒绝；读取 error_code 与 diagnostics，不当作成功 |
| HTTP 200 + unconfirmed_do_not_retry | 未确认结果；不要自动换去重键再次推送 |

飞书 `open_id cross app` 表示收件人 Open ID 属于另一个应用；必须获取本应用下的用户 ID。当前版本对部分上游 HTTP 错误仅记录 HTTPStatusError 与状态码，具体平台业务码可能需管理员排查，不能只凭 HTTP 400 判断原因。
