# HTTP API 参考与错误处理

**技术参考 · 适用服务 1.19.0。** 首次接入先看[教程](../tutorials/FIRST-INTEGRATION.md)，本页用于查询和故障决策。

首次接入总览见 [开发者接入指南](../integration/README.md)。机器可读规范见 [OpenAPI 3.1](../../server/openapi.json)，匿名可读服务地址后的 `GET /docs/openapi.json`（同源通用规范）；原 `GET /openapi.json` 仍需客户端鉴权并提供实例配置地址。公开文档不会开放管理 API、消息或私有接入包。下述 JSON 示例均为示意数据，不含真实凭据。

假设公开地址为 `https://notify.example.com/bridge`，下表的路径都相对于该地址。真实地址由部署者配置。

1.15.0 起，发送与查回执接受 `bot_id`，按当前 Key 的授权列表路由。`GET /api/status` 返回允许的 Bot 和默认 Bot；原 Key 仍默认使用原微信连接。完整规则见 [多 Bot 与 Key 授权](BOTS.md)。`channel` 是可选平台过滤条件，不能代替多个同平台 Bot 的明确选择。

下表除 `/health` 外的消息 API 需要 `Authorization: Bearer <API_KEY>`。新 nb_ 与旧数字 Key 均为字符串。收件人由服务器绑定确定，请求不能指定其他收件人。管理端仅使用独立账号 Cookie/CSRF；原管理员 Key 登录已移除，应用 Key 不能代替管理身份。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | /health | 进程健康 |
| GET | /api/status | 调用身份、接收状态、最近活动、下次心跳 |
| POST | /api/messages | 发送 Markdown 消息 |
| POST | /api/notifications | 发送任务提醒 |
| GET | /api/deliveries?dedup_key=... | 查询发送记录 |
| GET | /api/inbox?after_id=0&limit=20 | 按游标读取微信、飞书及网页回复 |
| GET | /api/conversations/{id}/history | 本应用完整已记录共享历史，单 before/after/around 游标，不改变手机已读 |
| POST | /api/inbox/{id}/claim | 显式领取所属应用消息，固定 request_id |
| POST | /api/inbox/{id}/report | 持 claim_id、固定报告 request_id，报告 processing/completed/failed |
| GET | /openapi.json | 当前配置对应的 OpenAPI |

## 条件性会话接收授权

所有客户端接口仍使用应用 Bearer Key 或 OAuth。访问 protected 会话内容、发送、任务、领取、续期、报告及监控回执，还必须携带已验证的 `X-Notify-Receiver` 能力头；应用 Key 本身不证明具体 AI 聊天身份。legacy 会话不因此增加必填头。

`/api/receivers/exchange` 使用私有配对码，不携带该头；`/api/receivers/verify` 使用待验证能力头和 challenge。注册及只读元数据的例外、观察者限制和完整流程见[接收绑定](../integration/RECEIVERS.md)。不要把令牌放进 URL、日志或提示词。OpenAPI 将该头声明为条件必需的可选参数，不会对旧客户端一律强制要求。

## 普通消息

v0.3 新增：读取只标 client_read，不等于领取或执行；claim 返回 claim_id，report 终态不可降级、重放须同键同内容。结果是应用报告。管理员主动新建会话的首条消息和回复 source=admin，与手机/原应用共享同一记录。参考 [完整 HTTP 业务闭环](../integration/HTTP.md)。Feishu not_sent 且保存未开始消息请求的证据时才允许保持原参数附 retry_preparation:true；未知、已接收和缺历史不支持重试。

```json
{
  "text": "实验完成了。",
  "dedup_key": "experiment-42-complete",
  "dry_run": true
}
```

`dry_run: true` 只校验，不外发微信或飞书；省略或设为 false 才实际发送。服务端根据密钥给正文加上 `[客户端名称]`。API 正文最多 20000 字符；微信展示内容（含标记和会话链接）最多 2000 字符，超出时发送短摘录。去重键最多 200 字符，不接受空白内容。调用方不能用 source 或 caller 参数覆盖身份。

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

在相同应用、会话和原目标的去重范围内，相同 dedup_key 与内容复用原记录；同键不同内容返回 HTTP 409。策略请求保留原来省略的目标，不把返回的实际 Bot 补回查询；显式 Bot 查询继续传原 Bot。不同客户端使用独立去重空间，查询发送记录也仅查本客户端。客户端改名或重置密钥不改变其稳定 ID，保留去重记录；旧版导入的客户端仍可查询原来的对应发送记录。`server-heartbeat-` 和 `server-command-` 前缀由服务器保留。

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
| not_sent | 已确认未开始平台消息请求；只在满足原请求证据时显式重试准备，不盲目重发 |
| muted | 正文/任务已保存，普通平台提醒被静音；不表示平台收件 |
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

多个聊天时，未提供 conversation_id 的发送返回 409 conversation_required，聊天已结束返回 409 conversation_closed，不属于本密钥返回 404。停用/删除客户端后不能发送，定向历史不会转入其他聊天或公共收件箱。legacy 聊天仅区分路由，不是额外鉴权边界；protected 会话另受本会话能力头约束，见条件性接收授权。服务只收存路由，宿主主动读取，不自动唤醒。

消息可包含文字和已支持的微信图片附件，按返回的附件 ID 获取，详见[图片与附件](IMAGES.md)；不等于支持任意视频/文件或飞书图片入站。所有外部内容都不能自动成为执行代码、审批或派发任务的授权。

可导入的静态接口描述见 [openapi.json](../../server/openapi.json)。其中域名是占位符，使用前替换；服务运行时的 `/openapi.json` 根据 WECHAT_PUBLIC_BASE_URL 生成实际地址。

## 管理页面与绑定接口

管理员账号 Cookie、同源与 CSRF 和应用认证分开；应用 Key 不能调用管理接口。操作及原管理接口表集中在[管理与恢复](../product-v3/OPERATIONS.md#管理接口补充参考)，本页不再复制。

## 管理客户端

Key 一次展示、正常轮换、泄露撤销和旧 rotate 的兼容影响见[应用与连接](BOTS.md)及[管理操作](../product-v3/OPERATIONS.md)。不把应用 Key 当管理凭据。

## 手机会话链接与全文（1.4.0）

`POST /api/messages` 的 `text` 接受最多 20000 字符。登记会话的出站正文加密保存，微信正文自动附加认证后的 `/chat/?c=<conversation_id>&m=<message_id>` 链接；2000 字符以内保留正文，超过微信长度预算时发送短摘录。链接不是访问凭证，不包含 API 密钥。未登记会话或未配置公开 URL 的长消息返回 422。

发送回执与查询回执增加 `message_id`、`conversation_url`。历史发送没有正文时两者可以为 null。dry_run 不创建历史，重复调用不创建第二条历史，失败发送也保留正文并明确标记微信提醒失败/未确认，不自动重发。

`GET /api/inbox` 同时包含对应聊天的网页回复（`source=web`），游标规则不变。服务在将消息返回给客户端时记录“客户端已读取”；这不代表模型已经处理或执行。网页回复不更新微信心跳或 context_token。参见 [CHAT.md](CHAT.md)。


## 完整客户端接口清单

路径、请求体、类型、必填/默认、长度/枚举/模式及规范声明响应已从 OpenAPI 自动投影到[HTTP 请求字段合同](../reference/HTTP-CONTRACT.md)。只修改实现并重新导出 OpenAPI，再生成该文档；不要手改第二套字段表。

当前 OpenAPI 对部分成功响应只声明空模型，不能由此推断具体 JSON 字段或断言错误不会发生。本页描述发送、收件和错误的运行语义；模型外校验仍以实现和回归为依据。原任务卡模式/选择约束集中在[任务卡片](TASK-CARDS.md)，图片返回形式见[图片与附件](IMAGES.md)。

## 错误处理与重试决策

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


### 先确定失败发生在哪一层

1. 请求未被服务接受：检查 HTTP/认证/参数；在发出平台请求前才能确认没有外发。
2. HTTP 200：仍解析 status、duplicate、error_code、diagnostics。平台拒绝、静音、未知结果不能记“送达”。
3. 网络超时 / 503：保留原请求，先 GET /api/deliveries 查原会话与去重键。不能把未拿到响应当作未发送。
4. 只有明确 not_sent、飞书消息请求尚未开始且原快照完整时，才可保持全部原参数加 retry_preparation:true 显式重试准备。它不是通用重试开关。
5. 回执 not_found 不自动证明永远未发送；同时检查原应用、会话、目标省略方式、服务状态和请求是否仍在途。不要因查错范围而换键再发。

### 收件处理冲突不是发送重试

| detail / 状态 | 原因与动作 |
|---|---|
| receiver_access_denied / receiver_scope_mismatch | 接收能力无效或不是本会话；停止内容访问，由管理员重新配对，不退回应用 Key |
| inbox_already_claimed | 活租约已有其他领取者；观察状态，不抢占或重复外部副作用 |
| inbox_claim_expired | protected 租约已过期；核对业务结果，使用新 attempt/request_id 接管，不重复旧领取键 |
| inbox_fence_mismatch | 代际/绑定/claim 不匹配；旧进程不能继续写结果，重新核对当前处理者 |
| request_id_content_conflict | 同一个报告键被用于不同内容；修正幂等记录，新状态使用新报告键 |
| inbox_processing_final | 已 completed/failed；不改终态，不自动重做业务 |

详细领取/离线顺序见[可靠收件原理](../explanations/RELIABLE-CONVERSATIONS.md)。API 的 `failed` 是应用报告的终态，不是服务承诺自动重试的队列。

### 安全排障记录

记录脱敏的时间、HTTP 状态、固定 detail/error_code、conversation_id、原目标与去重键、message_id、请求是否 dry_run、相关版本；不要保存 Authorization、接收令牌、验证码、完整敏感正文或平台 Secret。SDK 示例为防泄露只抛固定 HTTP 状态；需要 detail 时由受控后端安全解析响应，不把完整异常/配置打印到聊天。

每次只改变已确认的错误项，再以原业务键核对。没有真实收件就写“平台接受/未确认”；没有真实宿主就写“协议/SDK 验证”。管理界面问题查[管理员操作](../product-v3/OPERATIONS.md)，平台约束查[投递可靠性](DELIVERY-RELIABILITY.md)。
