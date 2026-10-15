# F02 隔离测试版本交付

> 历史阶段交付：下列验证状态属于 F02 收口时点。后续真实验收摘要见 ../history/release-1.17.0.md；当前接入以 ../integration/RECEIVERS.md 为准。

2026-10-15。隔离实现完成，等待用户体验确认；真实宿主及真人平台验收未完成。分支 codex/upgrade-after-stable-20261014，原稳定标签/生产/main均未修改，未推送或部署。

## 立即体验

- 管理端：http://127.0.0.1:19865/admin/
- 完整气泡闭环：http://127.0.0.1:19865/admin/#conversations?c=e693d0e22edd43afa59320832dc7eeb8
- 投递分流：http://127.0.0.1:19865/admin/#deliveries?view=routes
- 选择应用 f02验收-6bb07ee5；管理应用→通知分流；会话菜单→通知偏好/接收绑定/静音/停止。
- 登录资料仅在忽略的 .private/test-v03/local-access.json，不写在公开报告。当前浏览器会话已登录。测试期望平台收件与代理出口均为替身。

会话与手机复用共享气泡，当前首条消息、手机答复与原应用回复已留在测试数据中。没有后台业务Agent或长期收件器；仅保留供验收的本机Web进程。

## 已完成批次

| 批次 | 提交 | 实际结果 |
| --- | --- | --- |
| F02-0 | f8253d4 | 来源、差异/合同、兼容边界、基线与隔离恢复 |
| F02-1 | bcd4f65 | 接收能力/配对/主观察者、准确入站、待归属、双方创建 |
| F02-2 | d1f0674 | 租约/代际、订阅状态/补查、归档/静音/外部停止分离 |
| F02-3 | 当前分支F02-3独立提交 | 应用默认/会话偏好/授权紧急B、失败/备用/静音、统一界面、导出/最终回归 |

[实施与证据](IMPLEMENTATION.md)记录各批测试与兼容选择；[接收与恢复](../integration/RECEIVERS.md)提供可操作配置说明。当前功能已进入Vue/FastAPI，不是D0静态原型。

## 验收边界

| 基线场景 | 证据与结果 |
| --- | --- |
| V01～V04 | 同应用多个protected会话不增Key；待绑定首条保留；同Key另一能力跨读/领/报拒绝；唯一主接收者与并发单赢家。HTTP/SDK/浏览器通过，真实ChatGPT聊天未验证 |
| V05 | 租约过期重领递增代际；过期续期与旧报告拒绝；恢复保留代际。自动测试通过 |
| V06 | 持久事件挑战/到期/取消/重试/失败状态，回调失败仍补查，2xx不是执行。替身回调测试通过，Work/Dot真实订阅未验证 |
| V07 | 管理与手机共用任务；跨端并发答复仅一次决定；既有任务同步/投递失败回归通过 |
| V08～V09 | 归档后仍沟通；静音保留正文/任务；停止须正确领取与代际回执，超时未确认。浏览器/HTTP/自动测试通过，未运行真实业务监控 |
| V10～V12 | 普通A/偏好/授权B/去重/限频/一次任务备用，未知不改投；飞书引用准确归属，无引用待归属。真实HTTP+平台替身/浏览器通过，未验真人飞书鸣响 |
| V13、V15 | 旧Key/API/旧停用数据、断网/延迟/撤权/重复/重启/一致恢复回归通过；生产最新数据库未取样或恢复 |
| V14 | 真实stdio SDK与HTTP已验证；Codex/Claude/Work/Dot的具体聊天身份和后台唤醒均未验证；host_identity始终unverified |

服务端366通过，修正后插件/分流/导出30通过，前端6通过，构建/静态/文档/共享产物通过；仅既有anyio弃用警告。浏览器覆盖策略保存/重开、冲突拒绝/取消、正常/空/未知详情、390px窄屏。截图在父级deliverables/v03-evidence/f02-1-receiver.png、f02-2-lifecycle.png、f02-3-routing.png、f02-3-narrow.png。

## 复现及回退

使用原.venv，从仓库根运行 scripts/run_v03_test.py，仅绑定19865。scripts/verify_f02_test.py会检查服务为simulated环境，然后新建独立测试应用/两个替身Bot并验证HTTP闭环；scripts/verify_f02_mcp.py复用其私有配置验证真实stdio协议，不修改全局宿主配置。私有能力/Key只在忽略目录，输出仅非敏感结果。

F02-0已有修改前一致快照，F02-3又对当前本地库备份并恢复核验；这些是测试库。上线前须另获授权，使用最新生产一致备份+原密钥+匹配配置，在隔离无生产出口环境验证。升级失败先保全新增记录，再恢复匹配的稳定代码/升级前数据/原密钥/部署配置；禁止旧二进制直接用新库忽略权限/撤销字段。不能将覆盖旧快照称零数据丢失。

需要用户后续配合：确认本地操作体验；若继续真人验收，另提供独立测试Bot及目标宿主条件。当前不需要生产权限，不默认连接服务器旧Bot。未启动下一轮重构。

## 各批具体文件

### F02-0

```text
docs/f02/F02_正式设计基线.md
docs/f02/IMPLEMENTATION.md
docs/f02/SOURCE.sha256
scripts/build_release.py
server/src/wechat_bridge/web/admin/developer-kit.zip
```

### F02-1

```text
docs/f02/IMPLEMENTATION.md
frontend/build-manifest.json
frontend/src/admin/components/ReceiverPanel.vue
frontend/src/admin/components/UnassignedReplies.vue
frontend/src/admin/pages/Conversations.vue
frontend/src/shared/ConversationThread.vue
frontend/src/shared/conversation-thread.css
frontend/src/shared/errors.js
frontend/src/shared/receiver-state.js
mcp-plugin/server/http_bridge.py
mcp-plugin/server/receiver_store.py
mcp-plugin/server/toolkit.py
server/openapi.json
server/src/wechat_bridge/api/admin_conversations.py
server/src/wechat_bridge/api/clients.py
server/src/wechat_bridge/api/inbound_routes.py
server/src/wechat_bridge/api/receivers.py
server/src/wechat_bridge/api/schemas.py
server/src/wechat_bridge/api/security.py
server/src/wechat_bridge/app.py
server/src/wechat_bridge/channels/feishu/inbound.py
server/src/wechat_bridge/mcp/events.py
server/src/wechat_bridge/mcp/server.py
server/src/wechat_bridge/mcp/tools.py
server/src/wechat_bridge/services/admin_conversations.py
server/src/wechat_bridge/services/portal.py
server/src/wechat_bridge/storage/client_registry.py
server/src/wechat_bridge/storage/conversations.py
server/src/wechat_bridge/storage/database.py
server/src/wechat_bridge/storage/inbox_claims.py
server/src/wechat_bridge/storage/receivers.py
server/src/wechat_bridge/web/admin/app.js
server/src/wechat_bridge/web/admin/developer-kit.zip
server/src/wechat_bridge/web/admin/onboarding-template.zip
server/src/wechat_bridge/web/admin/style.css
server/src/wechat_bridge/web/chat/app.js
server/src/wechat_bridge/web/chat/style.css
server/tests/test_f02_inbound.py
server/tests/test_f02_receiver_adapter.py
server/tests/test_f02_receivers.py
server/tests/test_feishu.py
```

### F02-2

```text
docs/f02/IMPLEMENTATION.md
frontend/build-manifest.json
frontend/src/admin/components/ReceiverPanel.vue
frontend/src/admin/pages/Conversations.vue
frontend/src/chat/App.vue
frontend/src/chat/useChat.js
frontend/src/shared/ConversationThread.vue
frontend/src/shared/errors.js
frontend/src/shared/format.js
mcp-plugin/server/toolkit.py
server/openapi.json
server/src/wechat_bridge/api/admin_conversations.py
server/src/wechat_bridge/api/clients.py
server/src/wechat_bridge/api/lifecycle.py
server/src/wechat_bridge/api/portal.py
server/src/wechat_bridge/api/receivers.py
server/src/wechat_bridge/api/schemas.py
server/src/wechat_bridge/app.py
server/src/wechat_bridge/mcp/events.py
server/src/wechat_bridge/mcp/tools.py
server/src/wechat_bridge/services/admin_queries.py
server/src/wechat_bridge/services/portal.py
server/src/wechat_bridge/storage/conversations.py
server/src/wechat_bridge/storage/database.py
server/src/wechat_bridge/storage/inbox_claims.py
server/src/wechat_bridge/storage/lifecycle.py
server/src/wechat_bridge/web/admin/app.js
server/src/wechat_bridge/web/admin/developer-kit.zip
server/src/wechat_bridge/web/admin/onboarding-template.zip
server/src/wechat_bridge/web/chat/app.js
server/tests/test_f02_leases.py
server/tests/test_f02_lifecycle.py
server/tests/test_f02_subscriptions.py
```

### F02-3

```text
docs/f02/DELIVERY.md
docs/f02/IMPLEMENTATION.md
docs/integration/AI-HOSTS.md
docs/integration/HTTP.md
docs/integration/RECEIVERS.md
examples/python/notify_bridge.py
frontend/build-manifest.json
frontend/src/admin/components/NotificationPolicy.vue
frontend/src/admin/components/NotificationRoutes.vue
frontend/src/admin/delivery-state.js
frontend/src/admin/pages/Conversations.vue
frontend/src/admin/pages/Deliveries.vue
frontend/src/admin/pages/Keys.vue
frontend/src/shared/ConversationThread.vue
frontend/src/shared/errors.js
frontend/src/shared/format.js
mcp-plugin/README.md
mcp-plugin/server/api_errors.py
mcp-plugin/server/http_bridge.py
mcp-plugin/server/toolkit.py
mcp-plugin/skills/wechat-notify/SKILL.md
mcp-plugin/skills/wechat-notify/references/channels.md
mcp-plugin/skills/wechat-notify/references/conversations.md
mcp-plugin/tests/test_stdio.py
scripts/verify_f02_mcp.py
scripts/verify_f02_test.py
server/openapi.json
server/scripts/build_onboarding_assets.py
server/src/wechat_bridge/api/clients.py
server/src/wechat_bridge/api/notification_routes.py
server/src/wechat_bridge/api/schemas.py
server/src/wechat_bridge/app.py
server/src/wechat_bridge/channels/router.py
server/src/wechat_bridge/mcp/errors.py
server/src/wechat_bridge/mcp/tools.py
server/src/wechat_bridge/services/notification_routing.py
server/src/wechat_bridge/services/onboarding.py
server/src/wechat_bridge/web/admin/app.js
server/src/wechat_bridge/web/admin/developer-docs.json
server/src/wechat_bridge/web/admin/developer-kit.zip
server/src/wechat_bridge/web/admin/onboarding-template.zip
server/src/wechat_bridge/web/chat/app.js
server/tests/test_f02_notifications.py
```
