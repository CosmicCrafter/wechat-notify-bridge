# 错误与恢复

工具执行失败通过 MCP isError 返回；错误文本可含 JSON 字段 code、message、http_status 和 next_action。旧服务器可能返回普通文本，因此不要依赖新字段必定存在。

| 情况 | 下一步 |
| --- | --- |
| http_401 / invalid_client_key | 用户重连 OAuth 或更新私有本机配置；不在聊天索取凭据 |
| http_403 | 当前身份无权访问；不切换客户端绕过 |
| conversation_closed | 核对用户是否继续原任务，恢复原 ID |
| conversation_name_conflict | 按会话参考处理冲突；不另建 ID |
| conversation_not_found / image_not_found | 核对身份和原始 ID，不猜测或宣称已读图片 |
| http_422 | 核对参数约束；不修改已提交发送事件的正文后沿用同一键 |
| http_429 | 暂停调用；发送操作先查原回执，不能直接重发 |
| network_error / invalid_response / 服务器错误 | 读取可在连接恢复后重读；发送先查原回执 |
| 去重键内容冲突 | 恢复原参数并查回执，不换键重发同一事件 |

发送失败不一定表示微信没收到。保留原 conversation_id、dedup_key 和完整参数。attempting、unconfirmed_do_not_retry、api_rejected 或查询失败时报告实际状态，不自动重发。not_found 也不能单独证明可以安全换键重发。

api_accepted / no_error_reported 可表述为“已提交微信接口，手机收件尚未确认”。phone_confirmed 仅引用已有人工确认记录；Skill 不自行产生该状态。duplicate=true 必须同时检查 status。

已有明确授权的正常调用无需重复确认；只有缺失身份、路由或业务决定需要澄清。
