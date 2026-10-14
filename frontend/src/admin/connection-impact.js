import { ElMessageBox } from "element-plus";
import { api } from "./session.js";
export async function confirmConnectionChange(
  bot,
  action,
  { repair = false } = {},
) {
  const impact = await api("bots/" + bot.id + "/impact");
  if (impact.last_recovery_protected && !repair)
    throw Error("这是最后一个已验证的管理员恢复连接。请先验证另一个恢复连接。");
  const apps =
    impact.applications
      .map(
        (a) =>
          a.name +
          (a.is_default ? "（默认连接）" : "") +
          (a.enabled ? "" : "（应用已停用）"),
      )
      .join("、") || "没有授权应用";
  try {
    await ElMessageBox.confirm(
      action +
        "“" +
        bot.name +
        "”。受影响应用：" +
        apps +
        "。" +
        (impact.recovery_bound
          ? repair
            ? "仅允许修复同一本人身份。修复后需重新验证恢复用途。"
            : "此连接也用于管理员恢复，请确保其他恢复连接可用。"
          : ""),
      "确认通信连接变更",
      {
        type: "warning",
        confirmButtonText: "确认变更",
        cancelButtonText: "取消",
      },
    );
    return true;
  } catch (e) {
    if (["cancel", "close"].includes(e)) return false;
    throw e;
  }
}
