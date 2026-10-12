export function date(value, fallback = "—") {
  if (!value) return fallback;
  const p = Object.fromEntries(
    new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Shanghai",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    })
      .formatToParts(new Date(value * 1000))
      .map((p) => [p.type, p.value]),
  );
  return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}`;
}
export const platformName = (p) => (p === "wechat" ? "微信" : "飞书");
export const connectionLabels = {
  disabled: "已停用",
  unbound: "待扫码绑定",
  waiting_message: "等待首条微信消息",
  connected: "接收正常",
  connecting: "连接中",
  retrying: "正在重连",
  session_expired: "绑定已失效",
  configured: "配置已保存",
};
export const taskLabels = {
  pending: "待答复",
  answered: "已答复",
  processing: "处理中",
  completed: "已完成",
  cancelled: "已取消",
  expired: "已过期",
};
export const deliveryLabels = {
  legacy: "历史消息",
  pending: "已提交 · 等待客户端读取",
  client_read: "客户端已读取",
  attempting: "已保存 · 通道发送结果待确认",
  api_accepted: "通道接口已接受",
  no_error_reported: "通道接口未报错",
  phone_confirmed: "已确认收到",
  api_rejected: "已保存 · 通道提醒发送失败",
  unconfirmed_do_not_retry: "已保存 · 通道提醒结果未确认",
};
