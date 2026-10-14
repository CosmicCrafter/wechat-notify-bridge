# Codex 与 Claude Code 接入

Notify Bridge 是站外通信服务。Codex、Claude Code 是调用方和维护助手；中转站不会启动内部 Agent，也不会恢复某个宿主旧聊天窗口。

## 先配置站，再配置客户端

在接入应用里建立独立身份、授权通信连接并保存一次展示的 Key。导出多个宿主资料仍使用同一个应用；导出不自动换 Key。权限以服务器授权为准，包内默认连接只是偏好。

本机 stdio 包调用 HTTP 服务，需要现有 Python 3.12+ 和已锁定 requirements。远程 MCP 使用公开 HTTPS 和用户 OAuth 授权，包里不含 Key 或 OAuth token。单独浏览器客户端不能访问你电脑的 localhost。

## 本机方式

解压私有包，按 INSTALL.md 使用原 tools/configure_client.py --prepare 建立包内环境。该工具只准备包，不写你的全局宿主设置、不发送通知。私有 .private/client.json 不提交 Git、不贴给 AI。请由人或受控凭据工具填入原 Key。

准备工具生成具有实际绝对路径的 mcp-client.json、claude-mcp.json 和 codex-config.toml。选择一种配置方式即可。Codex 把生成的表合入 ~/.codex/config.toml（项目作用域也可）；Claude Code 按原工具输出的 JSON 导入或在项目 .mcp.json 中配置。合入前核对现有同名服务器，保留其他配置，不重复安装插件和独立 MCP。

不运行 prepare 时，使用 codex-config.toml.example 的绝对路径占位；Codex TOML 示例不依赖任意环境变量路径展开。Claude 的 claude-mcp.json.example 使用 NOTIFY_BRIDGE_PYTHON、NOTIFY_BRIDGE_LAUNCH_SCRIPT、NOTIFY_BRIDGE_CREDENTIAL_FILE 三个路径变量，必须在宿主环境提供；不是把真实 Key 写入 JSON。

## 远程方式

Codex TOML 只需 mcp_servers 下的 URL，使用宿主 MCP OAuth 登录；Claude 导出 HTTP JSON 也仅含 URL。若选固定 Bearer Key，Codex 可用 bearer_token_env_var，Claude 可用独立 NOTIFY_BRIDGE_API_KEY 环境变量的 Authorization 引用。不要借用 AI 平台自身账号令牌；默认导出走 OAuth。

## 首次验收

1. 新宿主实际发现工具，getCallerIdentity.client_id 与导出配置一致。
2. 自己的新宿主聊天用稳定宿主 ID 注册；已明确指派的管理员会话 ID 则用 listConversations/getConversationHistory 核对并复用。
3. 在独立测试目标发送，查询同键回执；本人手机回复，同一应用 getMessages 收到。
4. 明确领取时 claimMessage；真正处理后 reportMessage，再向原会话回复。任务卡另用 updateTaskCard。
5. 确认历史与手机页一致。读取不等于领取、执行；报告是应用的陈述。
6. 自动唤醒/回调接收器另行配置并实测；能发现工具、能发通知都不证明自动唤醒。Claude/Codex 的宿主设置和能力可能不同。

## 文档依据

已于 2026-10-14核对配置形式：[OpenAI MCP 官方文档](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)、[Claude Code MCP 官方文档](https://code.claude.com/docs/en/mcp)。本地 SDK/协议和包内配置验证不等于新安装的真人宿主验收。
