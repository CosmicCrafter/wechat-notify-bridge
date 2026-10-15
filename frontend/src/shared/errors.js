export const errors = {
  bot_configuration_required: "连接尚未完成配置，不能启用投递，请先继续配置。",
  feishu_credentials_rejected:
    "飞书凭据验证失败，请核对 App ID 和 App Secret。本次修改未保存。",
  feishu_credentials_unavailable:
    "暂时无法连接飞书凭据校验服务，本次修改未保存，请稍后重试。",
  feishu_credentials_response_invalid:
    "飞书校验响应异常，本次修改未保存，请稍后重试。",
  urgent_not_authorized: "此应用尚未获授权使用紧急连接。",
  urgent_rate_limited: "紧急提醒过于频繁，请等待配置的间隔，不要换键重发。",
  urgent_bot_required: "请先选择紧急飞书 B。",
  urgent_bot_must_be_feishu: "紧急连接 B 必须是飞书。",
  notification_targets_must_differ: "紧急 B 须与普通默认及备用连接不同。",
  external_stop_confirmation_required:
    "外部监控尚未确认停止，请先发送停止请求并等待执行方回执。",
  inbox_claim_expired:
    "领取租约已过期。用新的领取请求接管同一消息，不要重发业务消息。",
  inbox_fence_mismatch: "领取代际或处理者已变更，迟到报告被拒绝。",
  monitor_stop_claim_required:
    "须先领取这条停止命令，并携带当前 claim_id 与 generation 确认。",
  receiver_primary_exists: "已有主接收绑定。确需换绑时，请明确撤销或勾选换绑。",
  receiver_protected_conversation_required:
    "这是旧应用级会话。请新建受保护会话；不会自动关闭旧客户端。",
  receiver_access_denied:
    "接收绑定无效、已过期或权限不足，请重新核对配对资料。",
  receiver_scope_mismatch: "接收能力不属于这条会话或不允许执行此操作。",
  receiver_pairing_invalid: "配对资料已使用或过期，请由管理员重新生成。",
  inbox_assignment_conflict: "消息已经归属到其他会话，不能再次改投。",
  http_requires_local_config: "HTTP 系统使用私有 HTTP 配置，无需远程 MCP。",
  admin_password_required:
    "修复最后恢复连接需要当前管理密码，并在修复后重新验证。",
  admin_not_initialized: "请由获授权的维护者使用服务器终端工具建立管理员账号。",
  invalid_admin_code: "验证码不正确、已过期或已使用，请检查后重试。",
  admin_code_retry_later: "验证码请求须至少间隔 60 秒，请稍后重试。",
  admin_code_send_unconfirmed: "验证码发送未确认，请检查恢复连接后再试。",
  recovery_connection_unavailable:
    "连接尚不可用于恢复；请先完成配置并收到本人消息。",
  last_admin_recovery_protected:
    "最后一个已验证恢复连接受保护，请先验证另一个连接。",
  verified_recovery_required: "请先验证一个恢复连接，再停用原管理 Key。",
  connection_test_retry_later: "连接测试须至少间隔 10 秒。",
  delivery_retry_unsafe: "此次投递不满足安全重试条件，请先核实原结果。",
  delivery_retry_history_incomplete: "历史请求资料不完整，不能自动复原发送。",
  client_receive_unavailable:
    "应用暂无有效接收凭据，请先恢复 Key 或 OAuth 授权。",
  credential_rotation_pending: "已有 Key 正在迁移，请先完成当前轮换。",
  credential_not_found: "Key 已变化，请刷新应用详情。",
  invalid_key_overlap: "Key 过渡时间须在 0–24 小时之间。",
  invalid_admin_credentials: "用户名或密码不正确。",
  invalid_admin_password: "密码须为 15–128 字符。",
  invalid_admin_username:
    "用户名须为 3–32 位中英文、数字、点、下划线或短横线。",
  admin_state_changed: "账号状态已改变，请重新登录。",
  admin_already_initialized: "已建立管理员账号，请登录。",
  admin_same_origin_required: "请求来源不匹配，请从本服务管理页面重试。",
  invalid_admin_request: "请检查账号参数；不允许额外字段。",
  admin_csrf_required: "安全会话已变化，请刷新后重试。",
  invalid_onboarding_settings: "接入参数不完整或格式不正确，请检查所选方式。",
  public_base_not_configured:
    "尚未配置服务公开地址，请先设置 WECHAT_PUBLIC_BASE_URL。",
  chatgpt_requires_remote: "网页 ChatGPT 需要使用远程 MCP。",
  remote_requires_https: "远程 MCP 需要可访问的 HTTPS 服务地址。",
  private_package_confirmation_required: "请先确认私有包保管说明。",
  client_key_mismatch: "Key 与所选身份不匹配，请核对原 Key；不会重置旧 Key。",
  client_disabled: "该身份已停用，请选择有效身份。",
  onboarding_template_unavailable:
    "接入包模板缺失，请管理员重新构建开发者资源。",
  incomplete_feishu_configuration:
    "启用飞书前请填写 App ID、本人 Open ID、App Secret、Verification Token 和 Encrypt Key。",
  feishu_owner_mismatch:
    "已有飞书应用与本人绑定不能替换，可修改 Secret 和回调密钥。",
  admin_not_configured:
    "尚未初始化管理员账号，请按登录页的服务器终端说明初始化。管理端不支持应用 Key 登录。",
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
