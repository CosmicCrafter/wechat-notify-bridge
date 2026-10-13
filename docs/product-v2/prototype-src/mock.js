export function seed(empty = false) {
  return {
    apps: empty
      ? []
      : [
          {
            id: "app_codex",
            name: "Codex-运维助手",
            target: "codex",
            enabled: true,
            bot_ids: ["conn_feishu", "conn_wechat"],
            default_bot_id: "conn_feishu",
            last: "09:40",
            hasNewKey: false,
          },
          {
            id: "app_backup",
            name: "每日备份任务",
            target: "http",
            enabled: true,
            bot_ids: ["conn_wechat"],
            default_bot_id: "conn_wechat",
            last: "09:42",
            hasNewKey: false,
          },
          {
            id: "app_erp",
            name: "ERP-订单服务",
            target: "http",
            enabled: true,
            bot_ids: ["conn_feishu"],
            default_bot_id: "conn_feishu",
            last: "09:31",
            hasNewKey: false,
          },
        ],
    connections: empty
      ? []
      : [
          {
            id: "conn_feishu",
            name: "飞书 · 运维通知",
            platform: "feishu",
            enabled: true,
            state: "ready",
            owner: "本人 · 飞书账号",
            last: "09:38",
            test: "待人工确认",
            app_id: "cli_demo_ops",
            owner_id: "ou_demo_owner",
          },
          {
            id: "conn_wechat",
            name: "微信 · 本人提醒",
            platform: "wechat",
            enabled: true,
            state: "ready",
            owner: "本人 · 微信账号",
            last: "09:24",
            test: "最近发送被拒绝",
            used: 10,
          },
          {
            id: "conn_feishu_new",
            name: "飞书 · 业务提醒",
            platform: "feishu",
            enabled: true,
            state: "pending",
            owner: "未配置",
            last: "—",
            test: "尚未测试",
            app_id: "",
            owner_id: "",
          },
        ],
    messages: empty
      ? []
      : [
          {
            id: "msg_1042",
            title: "每日备份报告",
            app: "app_backup",
            bot: "conn_wechat",
            at: "2026-10-14 09:42",
            status: "failed",
            code: "wechat_prepare_failed",
            ret: "-2",
            key: "backup-20261014-report",
            cid: "conversation_backup",
            detail: "平台返回 prepare failed，无法仅凭此判断额度或上下文问题。",
            next: "先直接在微信 Bot 发一条普通消息，再由调用方按原回执决定后续处理。新发言不会自动补发历史失败消息。",
            replies: [],
          },
          {
            id: "msg_1041",
            title: "磁盘使用率提醒",
            app: "app_codex",
            bot: "conn_feishu",
            at: "2026-10-14 09:40",
            status: "accepted",
            code: "no_error_reported",
            key: "disk-20261014-0940",
            cid: "conversation_ops",
            detail: "平台接口未报告错误；手机是否收到尚未确认。",
            next: "如需人工确认，请检查原会话的回复或任务答复。",
            replies: [
              { at: "09:41", source: "飞书", text: "收到，稍后检查。" },
            ],
          },
          {
            id: "msg_1040",
            title: "同步任务执行结果",
            app: "app_codex",
            bot: "conn_feishu",
            at: "2026-10-14 09:36",
            status: "unknown",
            code: "network_timeout",
            key: "sync-20261014-0936",
            cid: "conversation_ops",
            detail:
              "请求超时，未取得确定的上游结果。实际通知可能已被平台接受。",
            next: "先查询原 bot_id、conversation_id 与 dedup_key 的回执。不要换去重键、切换连接或自动重发。",
            replies: [],
          },
          {
            id: "msg_1039",
            title: "订单状态更新",
            app: "app_erp",
            bot: "conn_feishu",
            at: "2026-10-14 09:31",
            status: "accepted",
            code: "no_error_reported",
            key: "order-demo-42-updated",
            cid: "conversation_orders",
            detail: "平台接口未报告错误；未取得手机收件证据。",
            next: "保留原投递定位信息，按需查询会话回复。",
            replies: [],
          },
          {
            id: "msg_1038",
            title: "夜间任务异常",
            app: "app_backup",
            bot: "conn_wechat",
            at: "2026-10-14 09:20",
            status: "failed",
            code: "bot_access_denied",
            key: "night-task-demo-1",
            cid: "conversation_backup",
            detail:
              "调用方不具备请求连接的授权，通知未交给平台。此样本保留失败时权限，当前授权可能已调整。",
            next: "核对接入应用允许连接与请求 bot_id；调整授权前确认该应用应该调用此连接。",
            replies: [],
          },
        ],
  };
}
export const labels = {
  accepted: "平台已接受",
  failed: "投递失败",
  unknown: "结果未知",
  pending: "待配置",
  ready: "连接就绪",
};
export const sampleSecrets = {
  app_id: "cli_demo_new",
  app_secret: "DEMO_SECRET_NOT_VALID",
  owner_id: "ou_demo_user",
  verification_token: "DEMO_TOKEN_NOT_VALID",
  encrypt_key: "DEMO_ENCRYPT_KEY_NOT_VALID",
};
export function proxySeed(unconfigured = false, nodesEmpty = false) {
  return {
    available: !unconfigured,
    enabled: true,
    mode: "auto",
    manual_node: null,
    current_node: unconfigured || nodesEmpty ? null : "日本 Pro A",
    subscription_configured: !unconfigured && !nodesEmpty,
    subscription_label:
      unconfigured || nodesEmpty ? "未配置" : "subscription.example.test",
    source: "admin",
    update_hours: 6,
    check_minutes: 5,
    priorities: ["日本 Pro", "新加坡 Pro", "美国 Pro"],
    last_update: unconfigured || nodesEmpty ? "—" : "2026-10-14 09:30",
    next_update: unconfigured || nodesEmpty ? "—" : "2026-10-14 15:30",
    last_check: unconfigured || nodesEmpty ? "—" : "2026-10-14 09:40",
    last_error: "",
    current_unknown: false,
    health: unconfigured || nodesEmpty ? "未检测" : "上次完整回调检测通过",
    usage:
      unconfigured || nodesEmpty
        ? null
        : { upload: 1.2, download: 18.4, total: 120, expire: "2026-11-01" },
    nodes:
      unconfigured || nodesEmpty
        ? []
        : [
            {
              name: "日本 Pro A",
              type: "trojan",
              delay: 92,
              callback_ok: true,
              udp: true,
            },
            {
              name: "日本 Pro B",
              type: "ss",
              delay: 110,
              callback_ok: false,
              udp: true,
            },
            {
              name: "新加坡 Pro A",
              type: "vmess",
              delay: 86,
              callback_ok: true,
              udp: true,
            },
            {
              name: "美国 Pro A",
              type: "trojan",
              delay: 158,
              callback_ok: true,
              udp: false,
            },
            {
              name: "美国 Pro B",
              type: "socks5",
              delay: null,
              callback_ok: false,
              udp: false,
            },
          ],
  };
}
export function authSeed() {
  return {
    authenticated: false,
    username: "admin",
    password: "NotifyBridgeDemo123!",
    recovery_bot_id: "conn_feishu",
    recovery_owner: "本人 · 已验证的飞书账号",
    password_changed: "尚未修改",
    session_version: 1,
  };
}
