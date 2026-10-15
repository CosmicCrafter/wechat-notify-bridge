# 通知桥维护手册

源码版本 v1.18.0、MCP 插件 1.11.0，升级前保护基线 v1.17.1 / 8e1c03b；账号迁移、恢复绑定、经授权终端重置、升级备份和匹配回退见 [管理与恢复](product-v3/OPERATIONS.md)。本地替身验收与真人平台验收分开，不据此直接部署。

## 先理解职责

通知桥连接程序或 AI 与微信、飞书。调用方用独立 Key 获得指定 Bot 权限；服务负责发送、接收、会话、任务答复和回执。异常检测、业务审批执行、AI 唤醒后的行动由接入方负责。

目前采用单进程 Python + SQLite。前端为 Vue 3 + Element Plus 静态资源，MCP 插件独立调用 HTTP API。不需要 Redis、消息队列或服务器端 Node。不要将 uvicorn 改为多 worker。

具体 .env、SQLite、图片和密钥位置见 [配置与运行数据](server/CONFIGURATION.md)。

## 从哪里改

| 位置 | 职责 |
|---|---|
| `frontend/src/admin` | 管理页、Bot 向导、密钥权限、代理配置 |
| `frontend/src/chat` | 手机会话、草稿、附件与任务输入 |
| `frontend/src/oauth` | 授权登录和授权确认 |
| `frontend/src/shared` | 主题、弹窗尺寸、Markdown 净化和共享显示 |
| `server/src/wechat_bridge/api` | HTTP 路由与请求边界 |
| `server/src/wechat_bridge/channels` | Bot 注册、权限路由、平台驱动 |
| `server/src/wechat_bridge/services` | 消息、任务、手机门户、代理等业务逻辑 |
| `server/src/wechat_bridge/storage` | SQLite、加密数据与事务 |
| `server/src/wechat_bridge/runtime` | 服务初始化与生命周期 |
| `server/src/wechat_bridge/mcp` | 远程 MCP、OAuth 与宿主事件 |
| `server/src/wechat_bridge/wechat` | 微信协议与扫码绑定 |
| `mcp-plugin` | 独立宿主插件、技能与桌面接收器 |
| `scripts` | 构建、同步副本、检查、源码交付 |

前端只改 `frontend/src`。`server/src/wechat_bridge/web` 为需随 Python 包交付的生成产物，不是另一套源码。旧原生页面脚本和重复的 vendor 包已清理；升级后刷新旧页面。

插件中的共享工具和错误映射由 `scripts/sync_shared.py` 从服务器源码同步。不要两边分别维护。数据库表、包名和 `/wechat` 兼容入口沿用历史名称，不能仅为改名破坏客户端兼容。

## 文档与交付的权威来源

| 事实 | 唯一维护源与出口 |
|---|---|
| HTTP 路由、请求模型、接收授权头 | api/ 源码 → `create_app().openapi()` → server/openapi.json；API.md 解释操作语义，不另造接口 |
| 服务版本 / 插件版本 | wechat_bridge/__init__.py / mcp-plugin/plugin.json；项目清单及兼容插件清单必须一致，插件独立版本不随服务号猜测 |
| 网站七类帮助正文 | docs/integration、docs/server、product-v3/OPERATIONS.md → build_developer_kit.py → developer-docs.json；前端按 _sources 解析链接 |
| 公开文档站 | 同一用途白名单 → build_developer_kit.py 调用现有 marked 构建 HTML/Markdown/OpenAPI → public-docs.zip → /docs/；网页直接含正文，无运行时脚本。--check 比对输入与产物摘要，无需 Node |
| 开发者文档 ZIP | build_developer_kit.py 的用途白名单；排除历史设计，未收录源码链接明确指向完整仓库 |
| AI / HTTP 接入包 | 插件 Skill、CLIENT-SETUP.md、HTTP.md、RECEIVERS.md、示例和 OpenAPI → build_onboarding_assets.py → 模板；services/onboarding.py 仅在内存加入实例连接配置 |
| 独立插件 ZIP | mcp-plugin/tools/build_local_plugin.py 或 build_remote_plugin.py，复用同一安装说明与 Skill |
| 实例运行和恢复点 | 维护者受保护的镜像/挂载/备份清单；公开文档只给定位方法，不复制生产密钥或假定旧目录 |

RELEASE.json 中的 public_source_sha256 是 fingerprint_scope 指定的公开输入集合指纹（不同用途不能直接比较），不覆盖在线导出后加入的私有凭据，也不是生产备份或整个私有 ZIP 的校验和。插件内容变化需递增独立版本并保持身份；历史版本冲突见 REFINE-01 记录。独立远程包在 OAuth 保留旧前缀时应显式传 --mcp-url，优先使用站内导出的实际 mcp_url。

当前操作入口与历史材料分工见[文档索引](README.md)；历史验证范围保留到 history/，不把阶段记录中的“未验证”或“已上线”自动扩大到当前环境。

## 干净环境开发

使用 Python 3.12 和 Node 20.19+（或 22.12+），在仓库根目录执行：

```sh
python -m venv .venv
# 激活环境：Windows .venv\Scripts\Activate.ps1；Linux source .venv/bin/activate
python -m pip install -e ./server -r server/requirements-dev.txt -r mcp-plugin/requirements.txt
cd frontend
npm ci
npm run build
npm test
cd ..
python scripts/sync_shared.py
python server/scripts/build_developer_kit.py
python scripts/check_project.py
python -m pip check
python -m wechat_bridge --directory .private/local
```

运行命令输出本地访问地址；管理端使用账号密码，数据库建立后按[授权终端初始化说明](product-v3/OPERATIONS.md)建立账号，不生成管理Key或默认密码。此目录包含私有数据，不交付朋友、不提交Git。朋友应自行初始化自己的部署和凭据。

## 变更与验证

1. 功能变更只改所属模块；保持 Key、Bot、会话和幂等边界。
2. Python 使用 `ruff format server/src scripts mcp-plugin/server server/scripts examples`；前端在 `frontend` 运行 `npm run format`。
3. 前端修改后构建，共享定义修改后同步，文档修改后重建开发者资料包。
4. 运行 `python -m pytest -q`、`npm test`（frontend 目录）和 `python scripts/check_project.py`。
5. UI 用浏览器实际操作；涉及真实消息需单独验收。HTTP 200 不能当作手机已收件。
6. 构建源码包：`python scripts/build_release.py`；构建 wheel：`python scripts/build_wheel.py`。

纯文案或 CSS 小改采用定向检查；协议、权限、数据或生命周期变更运行完整回归。不要用生产 Bot 删除或真实审批做测试。

check_project.py 复用现有构建校验，并检查有效文档链接/锚点、服务与插件版本、工具清单对照、OpenAPI 条件接收头、JSON 请求示例和五类接入包与公开文档资源完整性。负向测试在 test_documentation_contracts.py，故意损坏版本、接收说明或必需文件必须失败；完整测试同时执行 HTTP 示例及解压后的 stdio 适配器。

需要独立本地网页验收时可运行 `python scripts/run_v03_test.py --port 19868 --directory .private/refine-01-test`；仅回环、随机管理凭据写入该私有目录，平台与代理均为替身。不要读取或复用生产配置；其他已有本地实例可保留。

## 发布与回滚

首次部署按项目首页进行；升级时不重新生成 secrets，不初始化新数据库覆盖旧库。

1. 保存当前镜像标识、Compose 配置和环境配置。核对实际挂载，通过 SQLite backup API 取得一致备份，或经授权停服后备份完整数据目录；保护配套原密钥。标准 Compose 路径只是示例，恢复以实例私有清单为准。
2. 在干净源码目录完成构建及验证；用 `server/Dockerfile` 构建完整镜像。不要依赖开发者电脑上的旧镜像逐层补文件。
3. 使用现有数据目录、密钥和端口启动候选镜像；检查 `/bridge/health`、管理员登录、Bot 列表、回调和必要的真实收发。
4. 发布失败先停新版本。无数据结构变化时可切回旧镜像；如涉及不兼容迁移，恢复配套数据库与密钥后回滚，不能只回滚代码。
5. 保留旧镜像和备份直到验收完成。生产日志不得记录密钥或消息敏感正文。

`/bridge` 是当前公共入口，反向代理保留旧 `/wechat`；OAuth issuer 不随页面改名随意变更。微信、飞书直连，只有配置的 AI 云端回调走代理。代理订阅属于运行配置，不能写入源码。

## 常见故障

- 页面旧样式：刷新页面，确认已运行前端构建，检查构建清单与线上资源。
- 飞书 Challenge/卡片失败：检查该 Bot 自己的 Encrypt Key、Verification Token、回调 URL 和应用发布状态；Open ID 与应用绑定。
- 微信推送失败：查回执、上下文和已用发送预算；不能无条件换去重键重发。网页回复不等于微信上下文刷新。
- AI 没自动回复：先检查消息是否进入对应会话，再查桌面/云端唤醒订阅，不要把通知送达与宿主唤醒混为一谈。
- 删除 Bot：停止连接并清理凭据、授权，历史消息保留；默认 Bot 删除标记防止重启自动恢复。

## 交付内容

交付源码 ZIP、构建清单及验证记录；不要交付工作区的 `.private`、`.venv`、真实 `.env`、SSH 密钥、消息数据库、订阅地址或管理员密钥。前端依赖由锁文件安装，第三方许可见 `frontend/THIRD-PARTY-NOTICES.md`。

当前交付并不自动授予开源许可；公开发布前由项目所有者确定适用许可证。
