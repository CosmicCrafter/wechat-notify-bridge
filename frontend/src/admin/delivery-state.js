export const deliveryStates = {
  api_accepted: ["平台已接收", "success"],
  no_error_reported: ["平台未报告错误", "success"],
  api_rejected: ["平台拒绝", "danger"],
  not_sent: ["准备失败，未发送", "danger"],
  unconfirmed_do_not_retry: ["结果未知，请勿重发", "warning"],
  attempting: ["发送中 / 尚无最终结果", "warning"],
  pending: ["等待应用领取", "info"],
  client_read: ["客户端已读取数据，未确认领取", "info"],
  claimed: ["应用已领取", "success"],
  processing: ["应用处理中", "warning"],
  completed: ["应用已报告完成", "success"],
  failed: ["应用已报告失败", "danger"],
};
export const stateLabel = (s) =>
  deliveryStates[s]?.[0] || s || "历史记录缺少状态";
export const stateType = (s) => deliveryStates[s]?.[1] || "info";
