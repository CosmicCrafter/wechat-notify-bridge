# 微信通知插件

通过常驻通知桥发送本人微信消息和任务卡片、读取微信和手机网页的文字/图片回复。插件 1.8.2 保留身份 `wechat-notify-local`、Skill 名 `wechat-notify` 与中文显示名“微信通知”。服务器负责登录、数据与心跳，插件不另建微信会话。

`mode="form"` 支持按需填写 1–5 个字段（文本、下拉、数字、日期），要求服务端 1.13.0。优先选择能解决问题的最简单交互；通知不要求确认。手机页提供待办、置顶、搜索、改名和本浏览器草稿恢复，详见 [使用说明](../docs/mobile-experience.md)。

只需通知时调用 `sendMessage`；需要选择方案时调用 `sendTaskCard`，默认单选，也支持按需设置 `mode="multiple"`（多选）、`mode="confirm"`（按钮确认）或 `mode="input"`（独立输入）。通过 `getMessages` 接收带任务 ID 的决定；用 `getTaskCard` 查询，用 `updateTaskCard` 更新实际处理状态。详见 [任务卡片](../docs/server/TASK-CARDS.md)，三种新模式要求服务器 1.12.0，原单选兼容 1.11.0。

## 选择接入方式

| 方式 | 适合情况 | 本机依赖 |
| --- | --- | --- |
| 远程 MCP（Streamable HTTP + OAuth） | 宿主支持远程 MCP 与 OAuth | 无需安装 Python |
| 本机 stdio | 宿主运行本地 MCP 进程 | Python 3.12 与 requirements.txt |

两种方式连接同一服务器，每个宿主分别授权。同一宿主通常只启用一种，避免同名工具重复。插件安装不会自动配置唤醒。

## 远程接入

先部署通知桥，然后在项目根目录生成带自己服务地址的插件：

```bash
python mcp-plugin/tools/build_remote_plugin.py --base-url https://notify.example.com/wechat --output dist/wechat-notify-remote.zip
```

将 ZIP 导入支持该插件格式的宿主。连接时通过 OAuth 页面登录并选择已有客户端身份；手机登录码在微信发送 `/web` 获取，不需要把 API 密钥粘贴给 AI。插件包的地址必须换成自己的部署地址，示例地址不能用于实际通信。

仅支持 MCP 的宿主也可以配置服务器的 `/mcp` 端点；其 Skill 加载方式由宿主决定。远程连接不等于任何宿主都支持自动唤醒，详见项目中的 `docs/server/REMOTE-MCP.md` 和 `docs/server/MCP-EVENTS.md`。

## 本机 stdio 接入

在插件目录执行 `python -m pip install -r requirements.txt`。微信发送 `/getkey codex` 或在 Admin 创建独立客户端，将地址和 40 位数字密钥存入私有配置：

```json
{
  "base_url": "https://notify.example.com/wechat",
  "api_key": "这里填写密钥，按字符串保存"
}
```

默认位置为 Windows 的 `%USERPROFILE%/.config/wechat-notify-bridge/client.json` 或 Linux/macOS 的 `~/.config/wechat-notify-bridge/client.json`。配置只允许本人访问，不放入插件或 Git 仓库，也不发到 AI 聊天。

| 环境变量 | 用途 |
| --- | --- |
| WECHAT_NOTIFY_CREDENTIAL_FILE | 自定义配置文件；JSON 跨平台，DPAPI 仅对应 Windows 用户可读 |
| WECHAT_NOTIFY_BASE_URL、WECHAT_NOTIFY_API_KEY | 同时设置时覆盖文件配置 |
| WECHAT_NOTIFY_PYTHON | launch.py 使用的 Python 解释器 |

也可在 JSON 中添加 `python` 指向已安装依赖的解释器。MCP 初始 command 仍需能启动 Python；通用 MCP 客户端可直接填写解释器绝对路径，参考 [配置示例](examples/mcp-client.json)。

Codex 本地目录安装参考 [marketplace 示例](examples/marketplace.json)：将示例保存到仓库的 `.agents/plugins/marketplace.json`，source.path 相对仓库根目录指向 mcp-plugin。发布 ZIP 的根目录则必须是 `wechat-notify-local/`，由下面的构建命令生成：

```bash
python tools/build_local_plugin.py --output ../dist/wechat-notify-local.zip
```

不同 AI 客户端设置不同私有配置路径，以免共享默认文件而被识别为同一个身份。密钥重置后更新配置，客户端改名无需换密钥。

## 9 个工具

| 工具 | 行为 |
| --- | --- |
| getCallerIdentity | 查询服务端确认的身份、连接状态和心跳时间 |
| registerConversation | 为当前聊天登记稳定 ID 与简称，不发微信 |
| listConversations | 列出本身份下的会话；include_closed 包括归档 |
| setConversationActive | 归档/恢复原会话；恢复同名冲突会失败 |
| sendMessage | 发送普通正文；dry_run 不发微信 |
| sendNotification | 发送任务、情况、所需操作组成的提醒 |
| getDeliveryStatus | 查询原去重键对应的发送结果 |
| getMessages | 读取指定会话的微信/网页回复，并更新客户端已读状态 |
| getImage | 将附件作为真实图像内容交给支持图像的宿主 |

首次连接先查询身份，再登记当前聊天。保存 conversation_id；后续发送、读取和查回执都传入它。完整流程在 [Skill](skills/wechat-notify/SKILL.md)。同一密钥下的会话只有路由区分，不构成独立安全隔离。

发送意图或明确任务通知规则是发送依据；安装不代表所有任务都可自动通知。API 接受不证明手机收件；发送超时保留原正文和去重键，先查回执，不盲目重发。图片当前支持从手机上传后由 AI 读取，不支持 AI 通过工具发图。

## 自动唤醒与能力边界

桌面需要单独配置 [实验性接收器](DESKTOP-WAKE.md)，云端需要宿主支持并订阅事件。桌面内部接口不是稳定公开 API，接收器仍保留实验性定位。接入 MCP、读到消息和实际唤醒 AI 是三个不同结果。

归档会话历史可读，但不能收发；有效会话不能同名。MCP 没有删除、改名或启用唤醒工具，不应让 AI 编造调用。

## 开发与验证

在完整项目根目录运行：

```bash
python scripts/sync_shared.py
python scripts/check_project.py
python -m pytest -q
```

工具和错误处理的原本位于服务器的 `mcp/tools.py`、`mcp/errors.py`，通过同步脚本生成插件中的 toolkit.py 和 api_errors.py。不要分别修改副本。插件主清单和兼容清单的身份、版本、展示文案保持一致；默认提示词维持原值。

本次依据与检查记录见完整项目中的 `docs/plugin-design.md`。源码/测试通过不等于宿主已安装新版，也不代表云端已发布。
