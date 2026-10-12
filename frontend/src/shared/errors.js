export const errors = {
  incomplete_feishu_configuration:
    "启用飞书前请填写 App ID、本人 Open ID、App Secret、Verification Token 和 Encrypt Key。",
  feishu_owner_mismatch:
    "已有飞书应用与本人绑定不能替换，可修改 Secret 和回调密钥。",
  admin_not_configured:
    "服务器尚未配置管理员密钥，请按部署说明添加管理员配置后重启。",
  confirm_rebind_required: "已有绑定，请确认后重新绑定。",
  pairing_retry_later: "请稍等几秒再生成二维码。",
  no_verification_pending: "验证码步骤已变化，请按当前提示继续。",
  pairing_session_changed: "连接状态已变化，请刷新状态后再试。",
  invalid_client_name: "名称请使用 1–32 位中英文、数字、下划线或短横线。",
  reserved_client_name: "这个名称由系统保留，请换一个名称。",
  client_exists:
    "这个客户端名称已存在。原密钥未改变，可在列表中选择“重置密钥”。",
  client_not_found: "该客户端已不存在，请刷新列表。",
};
const proxyErrors = {
  proxy_manager_not_configured:
    "代理管理尚未启用，请按部署说明配置 Mihomo 和私有控制文件。",
  proxy_control_configuration_invalid:
    "代理控制配置无法读取，请检查私有控制文件和权限。",
  proxy_operation_running: "正在处理上一次操作，请稍候。",
  invalid_proxy_settings: "请检查订阅地址、更新间隔和优先规则。",
  invalid_subscription_url:
    "订阅地址必须是公网 HTTPS 地址，不含用户名、密码或片段。",
  subscription_address_not_public: "订阅或节点地址必须指向公网。",
  subscription_download_failed:
    "订阅下载失败，请检查地址、证书或网络。保留上次可用配置。",
  subscription_too_large:
    "订阅超过 2 MiB，请使用较小的 Clash / Mihomo 节点订阅。",
  invalid_subscription_content:
    "订阅内容无法导入，请提供 Clash / Mihomo YAML 节点订阅。",
  subscription_has_no_supported_nodes: "订阅中没有支持的节点类型。",
  proxy_controller_unavailable:
    "无法连接 Mihomo 控制接口，请检查代理服务与私有配置。",
  proxy_no_available_node:
    "当前规则下没有可用节点，请检查订阅、优先规则或手动选择。",
  proxy_subscription_required: "请先保存订阅地址。",
  proxy_node_not_found: "该节点已不存在，请刷新列表。",
  proxy_operation_failed: "代理操作未完成，请检查连接后重试。",
  proxy_rollback_failed:
    "恢复旧代理配置失败，请管理员检查代理服务；不要继续更新配置。",
};
Object.assign(errors, proxyErrors);

Object.assign(errors, {
  bot_name_conflict: "Bot 名称已存在。",
  invalid_bot_settings: "请检查应用 ID、Open ID 和凭据格式。",
  bot_binding_conflict: "该账号已绑定到另一个 Bot。",
  invalid_bot_grants: "默认 Bot 必须在授权范围内。",
  bot_disabled: "请先启用此 Bot。",
});
