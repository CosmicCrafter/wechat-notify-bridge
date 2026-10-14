# 会话、接收绑定与生命周期

同一应用可动态创建多个会话，无需逐会话申请 Key。legacy 会话只区分路由，不提供聊天权限隔离。protected 使用额外会话能力，证明持有权限，不证明具体宿主聊天身份。

保存稳定 conversation_key 和 conversation_id；名称只用于展示，不按同名、在线状态或最近活动接管。管理员已指定 ID 时复用它，protected 待绑定时请管理员提供私有配对文件，不另建同名会话绕过。registerConversation(receiver_mode="protected") 仅限维护者已为本上下文配置独立 receiver_file 的本机适配器；令牌由适配器保存，不贴给 AI。远程注册缺少安全私有存储时会拒绝，不退回无权限收件。

受保护会话 reply_tag 为稳定 conversation 标签，显示名不是接收地址。飞书优先引用原通知/卡片；无明确关联进入待归属，由管理员明确分配，不自动回答唯一任务。手机已认证会话页直接回复可精确归属。

## 离线与领取

getMessages 按本会话保存 next_after_id；事件失败仍用持久收件补查，不新开未经授权的长期轮询。claimMessage 返回 claim_id、generation 与 lease_expires；处理中按期 renewMessageClaim。过期后重新领取会递增 generation，旧报告不能覆盖新处理者。reportMessage 必须携带当前 generation，执行端还需按稳定 inbox_id 保证自身业务幂等。只读观察者不能领取或报告。

## 三种控制

- 新 UI 归档只整理列表，不结束通信或事件订阅；取消归档不复活历史已停用会话。
- 静音只抑制普通平台提醒，消息/任务仍保留；授权紧急提醒可越过静音。
- 请求结束监控会产生 stop_monitor 控制消息。真正执行端完成停止后，领取该命令并用 reportMonitorState(stopped) 携带 stop_id、inbox_id、claim_id、generation 回执；无回执只能称待确认。收到回执后结束通信与绑定/订阅。不能假装操作系统任务已验证。

setConversationActive 是保留的旧通信关闭/恢复接口，不等于新归档，也不能绕过运行监控停止确认。有效名称冲突需由用户决定，不关闭另一个会话绕过；删除无法用重新登记恢复。
