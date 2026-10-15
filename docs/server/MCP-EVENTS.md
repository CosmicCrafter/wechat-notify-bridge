# 宿主消息事件与回调

这是与旧版 MCP 工具共存的事件兼容适配层，不替换微信接收器。

在同一鉴权 `/mcp` 端点提供 `server/discover`、`events/list`、`events/subscribe`、`events/unsubscribe`。事件名为 `message.created`，必须指定当前客户端名下启用的 `conversation_id`。普通工具仍由现有 SDK 处理；该版本不是对 MCP 2.0 全部能力的实现，网页 Work 已实测发现事件。具体历史验收见 [事件验证历史](../history/20261003-MCP-EVENTS.md)。

订阅使用加密持久化记录，默认最长一天，由宿主刷新。首次订阅从当前入站水位开始；刷新保留游标。仅用户的微信/手机页面直接消息产生事件，命令、心跳和发出的消息不产生事件。返回 `cursor: null`，不提供协议历史重放。

回调先进行签名 challenge 验证，再激活。HTTPS 只连接 DNS 解析后验证的公网 IP，保持原始 TLS 主机名，不跟随重定向。事件以 Standard Webhooks HMAC 签名，重试保留事件 ID。410、413 等永久错误停止，暂时错误最多尝试六次。订阅关联的 API Key 失效、应用撤销或真正关闭会话会停止投递；OAuth 授权失效后也停止。正常应用 Key 轮换不隐式撤销独立 OAuth，新的仅归档也不关闭通信。

服务端接受订阅或 webhook 返回 2xx 都不代表 AI 已回复。验收必须确认：宿主发现事件、成功订阅与回调校验、真实消息送达、目标 Work 聊天自动处理，以及取消订阅后停止。

## 回退

升级前备份数据库与配套密钥，按 [维护手册](../MAINTAINER.md) 制定镜像与数据回退方案。

此功能是独立于本机 desktop_relay 的云端路径。不要为同一个聊天同时配置两种触发方式。

## 可选的回调代理（1.6.4）

设置 `WECHAT_CALLBACK_PROXY_FILE` 为只读 JSON 配置文件路径，内容示例：

```json
{"host":"172.17.0.1","port":18093,"username":"callback","password":"REPLACE_LOCALLY","allowed_hosts":["connectors.api.openai.com"]}
```

这是管理员控制的出站配置，不能由事件订阅请求指定。启用时仅接受 `allowed_hosts` 精确匹配的 DNS 主机，使用带认证的 HTTP CONNECT 隧道和目标站点 TLS 证书校验；目标 DNS 由受信任代理出口处理，不受本机异常解析影响。代理也必须限制目标域名并拒绝其他目标。不自动回退直连，不跟随重定向；未启用时保持原有公网 DNS 校验和直连逻辑。

代理端口只绑定容器可访问的内部网桥地址，避免暴露到公网；代理凭据和节点订阅配置存于独立私有目录，不放进源码包。代理进程需设置开机启动和异常重启，域名白名单随真实宿主回调主机变化由管理员更新。部署前先验证代理下的 TLS 连接，再验证实际签名回调订阅。

### Docker Compose 中启用配置

标准 `server/compose.yaml` 默认不设置回调代理。准备好管理员控制的代理后，将 JSON 文件保存为服务器上的 `/absolute/private/callback-proxy.json`，限制读取权限，使容器 UID/GID `10001` 可读。该文件包含代理密码；不要将其放入公开仓库。

在 `server/` 的本机私有文件 `.private/compose.callback.yaml` 中添加：

```yaml
services:
  wechat-notifier:
    environment:
      WECHAT_CALLBACK_PROXY_FILE: /run/callback-proxy.json
    volumes:
      - /absolute/private/callback-proxy.json:/run/callback-proxy.json:ro
```

替换宿主机绝对路径。JSON 中的 `host` 和 `port` 必须能从容器内部访问；容器中的 `127.0.0.1` 不代表宿主机。示例网桥地址仅适用于对应 Docker 网络，实际部署应验证地址、认证和目标域名白名单。然后在 `server/` 中执行：

```bash
docker compose --project-directory . -f compose.yaml -f .private/compose.callback.yaml up -d --build
```

该配置仅控制事件回调出站，不改变微信登录、接收与发送路径，也不自动安装代理软件或下载节点订阅。取消代理时使用标准 Compose 配置重建服务即可；不配置代理的服务器需要能够直连实际宿主回调地址。节点导入、出口选择和代理进程维护由管理员负责。

## 授权隔离

订阅记录绑定 grant_id，令牌刷新保持此标识，撤销只影响该授权。不能用同一客户端的其他有效授权继续投递。升级前订阅缺少 grant_id，按拒绝投递处理，云端宿主需重新订阅。过期记录在订阅/取消时清理，active 且未过期的订阅最多 20 个；恢复失效记录也必须重新通过容量检查。
