# 通知桥客户端安装与接入

## 先选适合自己的方式

| 方式 | 本机准备 | 授权方式 | 下载后还要做什么 |
| --- | --- | --- | --- |
| 远程 MCP | 支持 Streamable HTTP 和 OAuth 的宿主 | 用户在浏览器授权 | 添加连接并完成 OAuth，不需要本机 Python |
| 本机插件 / stdio | Python 3.12+，可安装 requirements.txt | 私有客户端 Key | 准备运行环境，再安装插件或导入 MCP 配置 |
| 仅使用规则 | 宿主支持 Skill，或能读取规则文件 | 不含连接能力 | 另行配置 MCP；只有规则不能发消息 |

网页 ChatGPT 使用远程方式，不支持在网页中启动本地 Python。其他客户端是否支持 ZIP 插件、Skill 或 OAuth，以该宿主实际能力为准；不能将一种插件包当作所有客户端通用的安装器。

## 下载包里有什么

网站“快速接入”生成选定应用的接入包；“手动配置”提供无真实 Key 的模板或仅规则包；“接口文档”下载的是接入文档，不是可运行 MCP 插件。维护部署应下载完整源码，不能拿接入包安装服务器。

RELEASE.json 记录服务版本、独立插件版本及公开构建输入指纹；CONNECTION.json / DEPLOYMENT.json 提供实际地址。插件身份保持 wechat-notify-local，不能用服务器版本推断插件内容。fingerprint_scope 标明公开输入集合：developer-docs 是文档包，onboarding-template 是网站 AI/HTTP 模板，standalone-local/remote 是独立插件。不同范围指纹不同是正常的，只在相同范围比较；它不是整个私有 ZIP 的校验和。

已配置包的 `CONNECTION.json` 记录服务地址、接入方式、期望客户端身份和默认 Bot，不包含密钥。它描述路由偏好，不是服务器权限证明。

本机已配置包额外包含 `.private/client.json`，其中有真实 Key。整个 ZIP 和解压目录都属于私有文件，不上传公开仓库，不作为附件发给 AI，不让 AI 阅读这个私有文件。Skill 正文不含 Key。分享给另一位用户或另一台机器，建议生成另一把独立 Key。

服务器只存 Key 的哈希，不能还原原值。基于已有应用导出时，在管理页输入有效 Key 校验；丢失原值到原应用正常轮换，不为同一种导出另建重复身份。导出不自动换 Key。

“生成专用身份”只授权所选的一个 Bot，并将它设为默认。选择已有身份不会改变其授权：默认 Bot 仅影响省略 bot_id 时的路由；该身份的其他既有权限仍然有效。

## 本机包：准备环境

1. 将 ZIP 解压到长期保留、仅自己可访问的目录。不要只在压缩软件里双击运行，也不要放在会自动公开同步的目录。
2. 在插件目录（包含 INSTALL.md、requirements.txt 的目录）打开终端，检查 `python --version` 为 3.12 或更新版本。
3. 运行 `python tools/configure_client.py --prepare`。该命令创建包内 `.venv`，安装原 requirements，设置解释器，生成 `mcp-client.json`、`claude-mcp.json` 与 `codex-config.toml`；不会改全局宿主配置或发送消息。
4. Windows 若 `python` 不存在，可先使用 `py -3.12 tools/configure_client.py --prepare`。macOS/Linux 可使用已安装的 `python3`。必须先由用户安装 Python，包内不捆绑解释器。
5. 包移动到其他目录后重新运行配置工具，以刷新绝对路径。不要把 Windows 的 `.venv` 直接复制到 macOS/Linux。

独立插件 ZIP 不携带私有配置；如果缺少 `.private/client.json`，先创建仅本人可访问的 `.private` 目录，将 `examples/client.json` 复制到该位置并填写，已有文件不要覆盖。网站通用模板中的 `.private/client.json` 使用 `CONFIGURE_SEPARATELY` 占位符。先用本地编辑器填入自己的服务地址、Key 和可选 default_bot_id，再运行准备命令。地址不是管理页 URL，不能以 `/admin/` 结尾。远程地址必须 HTTPS；本机 stdio 可连接明确的回环 HTTP 地址，如 `http://127.0.0.1:8092`，不会放行局域网或公网明文 HTTP。

## Codex：选择一种安装路径

### 路径 A：安装插件，同时加载 Skill 和 MCP

网站完整接入包最外层包含 `.agents/plugins/marketplace.json` 和插件目录。独立插件 ZIP 没有此外层 marketplace，优先使用路径 B，不能直接套用下面的 marketplace 命令。使用支持插件的 Codex CLI：

```sh
codex plugin marketplace add "<完整解压根目录>"
codex plugin add wechat-notify-local@notify-bridge-download
```

本机包应先完成上一节的 Python 环境准备，再执行安装。只安装一次；不要同时再添加同名独立 MCP 连接。远程包安装后仍须在宿主里完成 OAuth 连接授权。插件安装/刷新方式以当前宿主版本为准，旧版本没有 plugin 命令时使用路径 B。

### 路径 B：仅配置 MCP，再单独加载规则

本机 stdio：将准备工具生成的 `mcp-client.json` 按宿主要求导入。Codex CLI 对应命令为：

```sh
codex mcp add wechat-notify --env WECHAT_NOTIFY_CREDENTIAL_FILE=<私有配置绝对路径> -- <Python绝对路径> <http_bridge.py绝对路径>
```

以上是参数模板，含空格的路径需加引号；不要把 Key 本身写入命令。Windows/macOS/Linux 的具体绝对路径可从 mcp-client.json 获取。

远程 MCP：从 CONNECTION.json 取出 mcp_url：

```sh
codex mcp add wechat-notify --url "<mcp_url>"
codex mcp login wechat-notify
```

MCP 添加成功不代表 Skill 已加载。按宿主支持的 Skill 目录或导入方式加载包内 `skills/wechat-notify/`；不支持 Skill 的宿主可参考规则文件，但不能保证自动应用。其他通用客户端填写服务地址或 command/args/env，不直接假设它接受 Codex 的配置格式。

Codex MCP 官方说明：https://developers.openai.com/codex/mcp 。上述 CLI 形态也已对照当前本机 `codex mcp`、`codex plugin` 帮助核对。

## 远程 OAuth 授权

打开宿主授权页，用通知桥一次性手机登录码登录，选择 CONNECTION.json 中的应用并确认授权。管理端“系统设置→手机端登录”生成该码；微信也可发 `/web`。纯飞书不需要先绑定微信。手机码和管理密码独立，不将码或令牌粘贴到 AI 聊天。

OAuth 由用户操作完成，ZIP 不会绕过授权，也不能静默替用户选择身份。完成后调用 getCallerIdentity，核对 client_id、授权 Bot 和默认 Bot；不一致时停止发送，重新选择正确身份。一个包的默认 Bot 说明不能代替服务端 Key 授权。

## 受保护双向会话

需要 F02 会话接收保护时，先读本包 F02-RECEIVERS.md（完整仓库为 docs/integration/RECEIVERS.md），为实际接收上下文配置独立 receiver_file，再注册或配对；默认 legacy 方式不会自动获得聊天强身份保护。详细宿主配置见 [AI 接入说明](AI-HOSTS.md)。不要将接收令牌交给模型。

## 三步验收，分别判断结果

1. **连接成功**：要求 AI 调用 getCallerIdentity，核对身份及所选 Bot；此步骤不发送通知。
2. **通知可用**：明确要求 AI 为当前聊天登记会话，先做 dry_run，再发送一条测试通知。使用相同业务事件的原参数和去重键查询回执；只有手机实际收件才能确认送达。
3. **回复 / 唤醒**：在飞书原生卡片、引用回复或微信对应会话中回复，要求 AI 用 getMessages 读取。自动唤醒还需单独配置宿主接收器或事件订阅，安装插件不自动启用。

可复制给 AI 的安全验收说明：

> 请读取插件中的连接说明（不要读取 .private/client.json），调用 getCallerIdentity 核对期望身份和 Bot。先只报告连接状态，不发送消息；我确认后再进行通知测试。每个聊天登记独立、稳定的 conversation_key，后续复用返回的 conversation_id。

## 常见问题与卸载

- 无工具：检查 Python 是否可执行、依赖是否安装、宿主是否加载 MCP；刷新连接或重启宿主。Skill 可见不代表 MCP 已连接。
- 401：Key 已失效或 OAuth 未授权；在本地配置文件更新 Key，或重新授权。不要反复在聊天中尝试密钥。
- 无权限 / Bot 不可用：管理员检查该身份的 Bot 授权、启用状态与平台配置，不擅自切换 Bot 绕过拒绝。
- 下载失败：不自动重试创建身份。先刷新“接入密钥”确认是否已经创建；已有 Key 无法取回，可停用未使用身份后重新生成。页面仍打开且已拿到文件时，可以重新下载同一份包。
- API 接受但手机没收到：查询原回执，检查平台限制；不能更换去重键盲目重发。
- 卸载插件只解除宿主连接，不撤销服务端 Key。丢失或泄露私有包时，在管理页停用/重置对应 Key，再重新配置；不要对仍在使用的其他身份做批量重置。

规则与连接配置只指导如何使用；服务器始终负责强制验证身份、Bot 权限和会话范围。
