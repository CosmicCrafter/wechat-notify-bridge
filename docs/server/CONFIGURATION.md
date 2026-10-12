# 配置与运行数据

## 为什么源码没有真实 .env

仓库交付 `server/.env.example`，真实 `server/.env` 是每个部署自己的配置，应被 Git 忽略。首次部署在 `server/` 下执行：

```sh
# Linux / macOS
cp .env.example .env
# Windows PowerShell
Copy-Item .env.example .env
```

不要覆盖正在使用的 `.env`。将 `WECHAT_PUBLIC_BASE_URL` 改为自己的 HTTPS 地址，例如 `https://notify.example.com/bridge`；示例域名不是已部署的服务。代理订阅可含访问令牌，因此真实 .env 不进入 Git 或交付 ZIP。

Docker Compose 从同目录 `.env` 读取插值，再将 compose 文件明确列出的变量传入容器。`.env` 不是任意 Python 程序自动读取的文件。使用 `python -m wechat_bridge` 的本机启动方式时，数据目录、监听地址由启动参数设置，不依赖这个 Compose 配置文件。

后台保存的代理订阅配置优先于 `.env` 初始值。Bot 凭据在管理页配置后加密存入数据库，不要求重复填入 .env。

## 安装依赖下载慢

Docker 默认使用 PyPI。国内网络可显式选择可信镜像来构建：

```sh
docker compose build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
docker compose up -d --no-build
```

这个构建参数只影响 Python 安装来源，不会给微信、飞书设置运行代理。安装后用 `python -m pip check` 检查依赖一致性。

## 三种运行位置

| 运行方式 | SQLite 数据 | 配套密钥 |
|---|---|---|
| 仓库标准 Compose | `server/.data/wechat.sqlite3` | `server/.private/provisioned/secrets/` |
| 本机 `--directory .private/local` | `.private/local/data/wechat.sqlite3` | `.private/local/secrets/` |
| 本机不指定 directory | 用户目录 `.notify-bridge/data/wechat.sqlite3` | 用户目录 `.notify-bridge/secrets/` |

容器内位置固定为 `/data/wechat.sqlite3` 和 `/run/secrets/`；真实宿主机位置由 volumes 决定，不能只凭源码目录猜测。自定义部署可通过 `WECHAT_DATA`、`WECHAT_SECRETS` 指定路径。

本机启动另生成 `admin-key.txt`，首次服务器初始化的管理员明文密钥保存在 `.private/provisioned/admin/admin.json`。这些文件只供管理员妥善保管，不公开、不发到聊天。

## 数据如何保存

使用 SQLite 持久化，数据不靠容器内存保存。数据文件名 `wechat.sqlite3` 是兼容名称，已同时存储微信和飞书数据。

- Bot 列表、Key 授权、会话标识、收发回执、任务状态与时间等结构化数据存在关系表中。
- Bot 凭据、消息正文、图片附件及部分敏感状态使用配套 `encryption.key` 加密为 BLOB。图片保存在数据库内，不是上传到第三方图床。
- 数据库不是整库加密；名称、标识、时间、状态等元数据可能明文保存，因此数据库本身仍是私有数据。
- 客户端认证保存不可直接当作原始 Key 使用的摘要；管理员认证也使用摘要。OAuth 与手机登录状态由各自存储逻辑管理。
- 输入草稿另存于浏览器本地存储，按身份隔离。未提交草稿不属于服务器数据库备份，图片选择等临时状态也不保证跨设备保留。
- 默认数据会持续保留，不承诺自动清空历史。按管理界面删除/归档规则操作，定期检查磁盘容量。

## 备份与恢复

备份必须同时包含数据库和原加密密钥；丢失加密密钥会导致已有加密内容无法恢复。不能生成新密钥代替旧密钥解密。

推荐停服务后备份整个数据目录、secrets 和私有部署配置。若启用 WAL，数据目录里的 `-wal`、`-shm` 也需一致处理；不要在服务写入时只复制一个 sqlite 文件作为可靠备份。

恢复时先停服务，将配套数据与原密钥恢复到对应挂载目录，核对容器运行用户权限，再启动并检查健康、登录及 Bot 状态。升级镜像不会自动删除绑定挂载的数据；不要使用删除卷或重新初始化的方式升级。

朋友部署新实例应自行生成新数据和新密钥；接管已有实例则需要在独立安全渠道接收原备份，源码 ZIP 不能代替数据迁移。
