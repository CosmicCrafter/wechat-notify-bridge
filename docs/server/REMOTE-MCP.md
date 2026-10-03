# 云端与本机 MCP

服务 1.9.1 在同一个常驻进程提供 `/mcp`（Streamable HTTP）。原 HTTPS API、微信绑定、空闲心跳和聊天记录保持共用。没有设置 `WECHAT_PUBLIC_BASE_URL` 时，不启用远程 MCP；生产必须设置实际 HTTPS 地址。

## 连接

1. 使用 `mcp-plugin/tools/build_remote_plugin.py --base-url https://notify.example.com/wechat --output remote-plugin.zip` 生成实际服务器地址对应的插件包。包中不放任何密钥。
2. 私人账号插件通过宿主的插件创建/安装功能注册；本机也可以安装这个包。支持 MCP 的其他宿主填写 `<公开地址>/mcp` 并使用 OAuth。
3. 首次连接跳转到授权页。在微信发送 `/web` 获取登录码，网页登录后选择已创建的客户端身份，例如 `codex` 或 `gpt`，再点“允许连接”。已有网页登录可直接选择身份。
4. 连接后调用 `getCallerIdentity` 校验身份；每个聊天调用 `registerConversation` 登记名称，并为收发工具传入独立 `conversation_id`。

原 stdio 本机插件仍支持私有 API 配置。每个宿主选择一种方式，避免重复启用相同工具。插件注册、OAuth 连接和宿主实际调用是三个不同的验证步骤。安装不代表自动轮询或自动唤醒 AI。

## 授权与撤销

- OAuth Authorization Code + S256 PKCE，动态客户端注册（DCR）；无密码/客户端凭证授权模式。
- 授权请求有效 10 分钟，授权码 2 分钟且只能交换一次；访问令牌 1 小时，刷新令牌 30 天。刷新时撤销旧授权令牌，刷新令牌不能重放。
- 授权/令牌请求必须携带准确 `resource=<公开地址>/mcp`；只授予 `wechat:bridge`。
- 令牌只存哈希；注册客户端秘密使用既有服务器加密密钥加密。重启后连接信息仍保留。
- 授权绑定现有 API 客户端和密钥版本。在 Admin 撤销、删除、轮换该客户端密钥，会立即使相关云端授权和刷新令牌失效；重命名保留授权。
- `/revoke` 支持宿主撤销该 OAuth 授权，不撤销其他连接。OAuth 令牌无法访问管理员接口或获得网页会话身份。
- 授权页需要网页本人身份验证和明确确认，不接受 MCP 工具代替用户授权；显示请求客户端和回调域名。
- 每个身份下的多个聊天是路由隔离；共享该身份的宿主能够访问同身份的全部聊天。

## 反向代理

保留原 `/wechat/` 代理，并关闭代理缓冲。由于服务位于路径前缀下，还须按 `server/deploy/nginx.conf` 添加两个明确的根级 discovery 路由：

- `/.well-known/oauth-authorization-server/wechat`
- `/.well-known/oauth-protected-resource/wechat/mcp`

只把这两个路径转发到微信服务，不能覆盖同域名的飞书 MCP discovery。若使用不同路径前缀，需要相应替换 discovery 路径。

首次部署前备份数据与加密密钥；保持一个服务进程、一个微信接收器。远程 MCP 本身不启动额外的微信会话。
