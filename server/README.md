# 常驻服务器

负责微信收发、API 鉴权、去重、消息存储和空闲心跳。仅服务已绑定的本人账号，客户端无法通过参数更换收件人。

## 文件职责

代码位于 `src/wechat_bridge/`，按 `api`、`services`、`storage`、`wechat`、`mcp`、`web` 分组；完整职责见 [项目结构](../docs/architecture.md)。部署入口保留在本目录，初始化脚本位于 `scripts/`，Nginx 示例位于 `deploy/`，接口文档集中在 [docs/server](../docs/server/)。

## 1. 初始化服务器配置

需要 Python 3.12、Docker Compose，以及手机微信中已开放的 ClawBot 入口。首次部署**无需先在 Windows 上扫码**。进入本目录 `server/`，生成服务端密钥和客户端配置；将示例 URL 改成自己的 HTTPS 地址：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python scripts/prepare_secrets.py --web-pairing --base-url https://notify.example.com/wechat
```

Windows 上可使用 `.venv\Scripts\python.exe` 执行相同工具。输出目录为 `.private/provisioned/`：

```text
provisioned/
├── secrets/
│   ├── encryption.key       服务器加密主密钥
│   ├── admin.json           管理员密钥哈希
│   └── clients.json         初始客户端哈希，默认空表
├── admin/
│   └── admin.json           管理页面地址与管理员密钥，仅交给管理员
└── clients/                 可选的初始客户端配置输出
```

初始化工具不打印密钥，也不会覆盖已有输出目录。这些文件不要提交 Git。管理员密钥与 MCP 调用密钥不同，两者不能互相使用。

默认先不创建 AI 客户端，扫码后从微信或 Admin 页面获取密钥。也可加 `--clients codex gpt` 预生成客户端配置，兼容旧版部署流程。

## 2. 启动服务

在服务器上的 `server/` 目录执行。容器只挂载服务端配置和数据，管理员原始密钥与客户端原始密钥不需要放进容器：

```bash
cp .env.example .env
# 编辑 .env，填写你的 HTTPS 地址。
mkdir -p .data
sudo chown -R 10001:10001 .data .private/provisioned/secrets
sudo chmod 700 .data .private/provisioned/secrets
sudo chmod 600 .private/provisioned/secrets/*
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:18092/health
```

将 [Nginx 示例](deploy/nginx.conf) 放入你已有的 HTTPS 站点。使用自己的域名和证书，确认 `nginx -t` 通过后 reload。示例将 `/wechat/` 请求体上限设为 `6m`，图片接口仍单独限制每张 5 MiB；不要沿用旧版 `32k` 配置，否则普通图片会收到 HTTP 413。Compose 默认只绑定回环地址，客户端通过 HTTPS 访问。

服务可在未绑定状态启动，不会主动发消息。通过网页完成绑定并收到首条消息后，空闲心跳开始计时：连续 12 小时无有效收发才尝试发送，正常沟通推迟心跳。心跳不能保证微信会话长期续期。

## 3. 打开网页扫码

1. 用电脑浏览器打开 `https://你的域名/wechat/admin/`。也可打开 `/wechat/`，自动进入管理页面。
2. 在服务器本机查看 `.private/provisioned/admin/admin.json`，使用其中的 `admin_key` 进入面板。不要把它填到 MCP 客户端。
3. 点击“生成二维码”，用**手机微信**扫一扫，在手机上确认连接。
4. 如微信要求输入连接数字，按页面提示填写。二维码过期后会在本次连接期限内自动刷新。
5. 进入手机的 ClawBot 对话，发送一句“测试”。页面显示“微信接收正常”后，通过 MCP/API 发送测试消息，并确认手机实际收到。接收正常不保证发送成功，发送受阻时面板会显示错误和恢复建议。

管理页面显示最近收发、下次空闲心跳、最近接收检查和累计接收条数。密钥仅放在页面内存中，刷新页面需重新输入；退出页面不会停止服务器。每次扫码最多持续 10 分钟，二维码最多自动刷新 3 次，也可手动取消。页面关闭后，未完成的扫码会在期限结束时停止。

新绑定直接加密保存在 `.data/wechat.sqlite3`，无需下载、迁移凭据或重启容器。尚未收到首条微信消息时发送接口返回 409，页面会提示下一步。重新绑定仅允许同一个微信账号；失败或取消不会在本地替换原有凭据，微信端是否撤销旧会话由其自身决定。

### 升级已有部署

保留已有 `.data/`、`encryption.key`、`clients.json` 和可选的 `bootstrap.enc`，不要重新初始化。如果旧部署还没有管理员配置，在原配置目录上执行一次：

```bash
.venv/bin/python scripts/prepare_secrets.py --admin-only --base-url https://notify.example.com/wechat
sudo chown 10001:10001 .private/provisioned/secrets/admin.json
sudo chmod 600 .private/provisioned/secrets/admin.json
docker compose up -d --build
```

配置目录不同可用 `--output <原 provisioned 目录>` 指定。此命令只增加管理员配置，不轮换加密密钥或 AI 客户端密钥。已有管理员配置时会拒绝覆盖。旧部署未添加管理员配置时，原有 API 可用，管理操作返回 503。

### 可选：导入旧绑定

已有兼容的私有绑定 JSON 可通过 `--credentials-json <文件>` 代替 `--web-pairing` 初始化。旧 Windows 工具仍保留于 `scripts/pair_wechat.py`；它使用 DPAPI，常规网页扫码不依赖 Windows。导入时生成的 `bootstrap.enc` 仅在数据库尚无绑定时使用。

## 4. 接入客户端

只绑定一个微信账号，每个 AI 客户端使用独立密钥。两种管理入口操作同一份数据：

- **微信**：在已绑定的 ClawBot 对话发送 `/getkey codex`，收到 40 位数字密钥。另一个客户端发送 `/getkey gpt` 或 `/getkey deepseek`。
- **Admin 页面**：在“AI 客户端”区域输入名称，创建密钥；列表中可改名、重置密钥、停用、重新启用或删除密钥。删除需在页面确认，确认后客户端从列表移除，旧密钥立即失效且不可恢复；保留历史消息，之后可用同名创建新的客户端和密钥。

把服务器 HTTPS 地址与对应密钥填入 MCP 配置。密钥必须按字符串保存，不能转换为数值。名字由服务器根据密钥识别，不需要让 AI 自报名称。收到的消息会自动标记 `[codex]` 等来源。

微信指令详见 [COMMANDS.md](../docs/server/COMMANDS.md)。`/help` 直接在微信返回简明说明，`/list` 返回名称、状态与最近调用时间，不显示原始密钥。已有名称再次 `/getkey` 不会重新生成；忘记密钥用 `/resetkey 名称`，旧密钥立即失效。改名保留密钥和发送去重记录。

客户端接入方式见 [MCP 插件说明](../mcp-plugin/README.md)，HTTP 客户端使用 Bearer 密钥，接口见 [API 文档](../docs/server/API.md)。客户端需要具备 MCP 或自定义 HTTP API 接入能力；持有密钥本身不会为 AI 产品增加工具调用入口。

## 运行与维护

- 只运行一个 worker 和一个服务实例，避免多个进程同时接收同一微信账号。
- `.data/` 保存数据库；入站正文、微信凭据和上下文已加密。客户端长期只存密钥哈希；待发送的指令回复暂时加密保存，尝试发送后清除正文。登记会话的出站正文也加密保存在消息时间线；未登记会话的旧式发送仍只存哈希与结果。
- `clients.json` 中的旧客户端只导入一次。后续以数据库为准；停用、重置、改名或删除后，重启不会重新启用文件里的旧密钥。
- 微信管理指令仅处理本人发来的完整、非引用文字；超过 10 分钟的旧指令不执行。管理指令和密钥回复不提供给 MCP 的消息读取接口。
- 指令执行、回复排队与接收游标在同一事务中提交；重复消息不会重复创建或轮换密钥。回复结果不明时不自动重发，未收到密钥可从 Admin 重置或重新发送 `/resetkey 名称`。
- 同时备份 `.data/` 和 `encryption.key`；丢失主密钥后无法解密原数据。
- 重启不会清除去重记录、最近活动时间或接收游标。
- `/health` 证明进程可访问；`/api/status` 才包含接收状态与心跳时间。两者都不是手机收件确认。
- 日志命令：`docker compose logs --tail=50`。更新代码后重新构建，保留持久化目录。

## 测试

在项目根目录运行：

```bash
python -m pip install -e ./server -r server/requirements-dev.txt
python -m pytest -q server/tests
```

测试模拟微信接口，不发送真人消息。覆盖扫码、权限隔离、密钥生命周期、聊天登记、标签路由、含糊标签、指令重复投递、失败恢复、聊天去重隔离及重启持久化。覆盖手机登录、CSRF、防重复回复、历史分页、加密存储与失败回执。当前实现不包含多个微信账号或自动唤醒 AI 任务。

## 手机会话页

服务地址后加 `/chat/`。在微信发送 `/web`，用收到的一次性码登录；也可在 Admin 的“手机会话页”生成登录码。支持 Markdown、历史记录、消息定位和直接回复。详见 [手机会话页说明](../docs/server/CHAT.md)。

## 云端与本机插件

服务 1.9.1 提供 OAuth 授权的远程 MCP；插件 1.5.0 可生成云端与本机共用的远程连接包。原 stdio 接入仍可用。详见 [远程 MCP 接入与授权](../docs/server/REMOTE-MCP.md)。

### 1.8.2 安全维护

OAuth 事件订阅绑定具体授权，刷新令牌延续授权关系，撤销后停止该授权的回调。旧版未记录授权归属的 OAuth 订阅会停止投递，需要在云端宿主重新启用一次；API 密钥订阅和桌面接收器不受此迁移影响。未获本人同意的 OAuth 客户端注册只保留 10 分钟，在启动、注册或查询客户端时回收；已授权客户端保留。订阅配额仅统计未过期的 active 记录，过期记录在后续订阅操作时清理。

本地开发启动（先安装本包并准备 `WECHAT_DATA`、`WECHAT_SECRETS`）：`python -m uvicorn wechat_bridge.app:app --host 127.0.0.1 --port 8092 --workers 1`。不要再使用旧的 `app:app` 导入路径。
