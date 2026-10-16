# 工程案例证据与验证边界

本页是案例的精简证据目录，不复制私有消息、部署路径、账号或备份。代码与自动测试可以随源码核验；真人平台和生产恢复原始记录由维护者受保护保存，不公开原始数据。

| 结论 | 当前实现 / 可复核测试 | 能证明与不能证明 |
|---|---|---|
| 单 Key 多会话与能力拒绝 | api/receivers.py、storage/receivers.py；test_f02_receivers.py 的双范围、观察者、撤销、重开测试 | 应用/会话能力控制；不证明真实 AI 窗口强身份 |
| 飞书明确引用而不猜目标 | channels/feishu/inbound.py；test_f02_inbound.py | 受控回调/路由条件；替身测试不等于真人平台 |
| 领取竞争、接管与旧代际拒写 | storage/inbox_claims.py；test_f02_leases.py | 两并发竞争、受控过期、续期和恢复；不证明大规模性能或外部恰好一次 |
| 订阅取消/过期与补查 | mcp/events.py；test_f02_subscriptions.py | 持久收件与订阅生命周期；不等于宿主自动唤醒 |
| 归档/静音/停止分开 | storage/lifecycle.py；test_f02_lifecycle.py | 状态与授权回执；不证明 OS 进程已物理停止 |
| 通知策略与未知不改投 | services/notification_routing.py；test_f02_notifications.py | 默认/偏好/显式/紧急/静音/备用和幂等；不保证手机鸣响 |
| 文档与独立包 | build_developer_kit.py、build_api_reference.py、check_documentation.py；test_doc02_content.py、test_documentation_contracts.py、mcp-plugin/tests/test_packages.py | 源/工件、反向守卫、示例与独立构建；不等于真实宿主、生产公网 |

上述路径相对于完整仓库的 server/src/wechat_bridge、server/tests、server/scripts 或 scripts；名称是查找入口，不把未推送候选的 GitHub 链接伪装成已公开证据。

## 历史事实的准确引用

- release-1.17.0 的历史摘要记录 F02、特定 Codex 主动调用、飞书双向及 R3 数据副本恢复的范围；它没有声称所有 Claude/Work/Dot 宿主自动唤醒通过。
- 已发布 a33517f 的[托管 CI](https://github.com/CosmicCrafter/wechat-notify-bridge/actions/runs/38778810721)实际验证当时版本。它不代表 DOC-01/DOC-02 候选已经运行托管 CI。
- 仓库 docs/history/doc-01.md 记录后续本地 443 项、浏览器和无历史 AI 接入；SDK 发现工具与真实宿主界面导入分开。
- DOC-02A 的清单、B 的 62 项定向验证已记录于仓库 docs/history/doc-02.md；完整 D 结果应以其最终章节与交付验收记录为准。没有执行的项目不补写 PASS。

验证记录需给出对象、版本/提交、执行方法、实际结果和局限。没有权限或资源时写 BLOCKED；尚未执行或证据不足写 UNVERIFIED；FAIL 是实际不满足要求，不能删掉或改名来掩盖。工程案例不包含未经测量的性能指标。
