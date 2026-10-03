# 项目结构与维护约定

项目由两个可独立交付的组件组成：`server/` 是常驻服务，`mcp-plugin/` 是 AI 宿主的连接适配。项目根目录的 `docs/`、`scripts/` 和 `pytest.ini` 提供统一文档、发布与验证入口。

## 服务器

所有运行时代码都在 `server/src/wechat_bridge/`，使用完整包名导入。`pyproject.toml` 将 Python 模块和页面资源一起打包，启动不依赖当前工作目录。

| 位置 | 职责 |
| --- | --- |
| `app.py` | 创建 FastAPI 应用、鉴权、异常映射、后台任务生命周期 |
| `config.py` | 公共 URL、Cookie 常量和静态资源根目录 |
| `api/admin.py` | 管理员密钥和扫码配对路由 |
| `api/clients.py` | 客户端消息、会话、图片、回执和事件游标 API |
| `api/portal.py` | 手机登录、历史、图片上传、回复、归档和删除路由 |
| `api/schemas.py` | 管理端和客户端请求模型 |
| `services/bridge.py` | 微信持续接收、发送、去重协调和空闲心跳 |
| `services/commands.py` | 微信文字指令和回复模板 |
| `services/portal.py` | 手机会话历史、登录状态和已读状态 |
| `storage/database.py` | SQLite 初始化、兼容迁移和持久化状态 |
| `storage/client_registry.py` | 客户端身份与密钥 |
| `storage/conversations.py` | 会话名称、状态与路由 |
| `storage/images.py` | 图片验证、规范化、额度与加密存储 |
| `wechat/protocol.py` | 微信域名校验、协议错误与响应语义 |
| `wechat/pairing.py` | 二维码配对和验证流程 |
| `mcp/server.py` | MCP 工具与认证组件的组装 |
| `mcp/oauth.py` | OAuth 授权、令牌与授权页面路由 |
| `mcp/events.py` | 事件订阅、回调签名和投递 |
| `mcp/tools.py` | 远程和 stdio 两端共用的工具定义原本 |
| `mcp/errors.py` | 两种传输共用的安全错误分类与恢复提示 |
| `web/admin/`、`web/chat/`、`web/oauth/` | 三种页面的 HTML、CSS、JS |
| `web/vendor/` | 随包交付的第三方资源、版本记录和许可证 |

这是一个单进程服务，数据库访问和业务协调沿用已有机制。`Store` 负责装配存储组件和会话服务；这些组件通过传入的 store 协作，不反向导入应用入口。当前并未强行改造成完全独立的领域层，也不支持通过增加 worker 数量扩容。

## 插件和共用文件

`mcp-plugin/server/` 保留脚本式入口，便于 AI 宿主用绝对路径启动 stdio 进程。它只调用服务端 API，不直接访问微信或数据库。插件独立分发时不依赖服务器源码。

以下文件由 `python scripts/sync_shared.py` 同步；发布前用 `--check` 检查：

- `server/src/wechat_bridge/mcp/errors.py` → `mcp-plugin/server/api_errors.py`
- `server/src/wechat_bridge/mcp/tools.py` → `mcp-plugin/server/toolkit.py`
- `docs/wechat-markdown/微信Markdown排版指南.md` → 插件 Skill 的 `references/wechat-markdown.md`

修改原本后运行同步工具，不要分别维护两份。插件版本与服务器版本独立；工具名称和默认值保持兼容，插件在本次使用规范优化中更新至 1.5.0。

## 开发和发布

在项目根目录安装依赖，执行 README 中的测试命令。服务器单独使用时，在 `server/` 下执行 `python -m pip install .`，入口为 `wechat_bridge.app:app`。初始化脚本统一在 `server/scripts/`。

源码包用 `python scripts/build_release.py` 构建，采用公开目录和文件类型白名单，排除缓存、虚拟环境和私有运行目录。不要向公开源码目录存放真实密钥；打包规则不能替代发布前的内容审查。远程插件包仍由 `mcp-plugin/tools/build_remote_plugin.py` 构建。

运行数据、加密主密钥和 OAuth 令牌继续保存在部署者自己的数据目录及 secrets 中，绝不能打包进 GitHub。升级时备份数据库与对应加密密钥；代码备份无法代替数据备份。
