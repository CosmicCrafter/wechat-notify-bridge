export const receiverLabel = (value) =>
  ({
    application_scope: "应用级接收（未隔离聊天）",
    waiting_binding: "待绑定",
    pending: "等待接收端验证",
    active: "接收权限已验证",
    revoked: "已撤销",
    expired: "已过期",
    pairing_expired: "配对已过期",
  })[value] || "状态未确认";
