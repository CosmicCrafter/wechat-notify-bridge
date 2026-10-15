// These commands are copied only; the browser never executes them.
export function recoveryCommand({
  environment,
  database,
  backup,
  username,
  initialize,
}) {
  const quote = (value) =>
    "'" +
    String(value).replaceAll(
      "'",
      environment === "powershell" ? "''" : "'\"'\"'",
    ) +
    "'";
  const prefix =
    environment === "compose" ? "docker compose exec wechat-notifier " : "";
  return (
    prefix +
    "python -m wechat_bridge.admin_reset --database " +
    quote(database || "<数据库绝对路径>") +
    " --backup-dir " +
    quote(backup || "<私有备份目录绝对路径>") +
    " --authorize RESET_ADMIN" +
    (initialize
      ? " --initialize --username " + quote(username || "<管理员用户名>")
      : "")
  );
}
