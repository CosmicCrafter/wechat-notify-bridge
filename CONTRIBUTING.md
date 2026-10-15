# 开发与维护

## 单一源码入口

- `server/src/wechat_bridge/`：Python 服务。`app.py` 仅装配依赖与路由。
- `frontend/src/admin/`：管理页 Vue 组件、功能页面和会话状态。
- `frontend/src/chat/`：手机会话页、任务交互与附件界面。
- `mcp-plugin/`：独立发布的宿主适配器。只调用 API，不直接访问数据库或平台凭据。
- `docs/`：接口、部署和维护规范；`examples/`：普通程序接入示例。

前端由 Vue 单文件组件维护，构建到 `server/src/wechat_bridge/web/`。不要直接修改生成资源。
管理页、会话页与授权页为独立入口，共享组件在 `frontend/src/shared/`。
构建方法见 [前端工程](frontend/README.md)。

## 本地开发

```sh
python -m pip install -e ./server -r server/requirements-dev.txt -r mcp-plugin/requirements.txt
cd frontend
npm ci
npm test
cd ..
python scripts/build_frontend.py
python scripts/sync_shared.py
python server/scripts/build_developer_kit.py
python -m wechat_bridge --directory .private/local
```

程序只监听 127.0.0.1。管理端使用独立账号密码；首次初始化及获授权终端恢复见[管理与恢复](docs/product-v3/OPERATIONS.md)。旧管理员 Key 不再用于管理端登录；应用 Key 保持独立。
本地微信可主动连接上游；飞书 HTTPS 事件回调需要一个公网可达地址和反向代理，单纯启动本地页面不等于回调接通。
不要将真实 data/secrets、会话内容或客户端凭据加入 Git。

## 检查与发布

```sh
python -m pytest -q
python scripts/check_project.py
python scripts/build_release.py
```

CI 同时检查 Windows 和 Linux。`scripts/check_project.py` 会只读核对开发者资料包及管理页文档与源文件是否一致；更新文档或接口后，运行 `python server/scripts/build_developer_kit.py` 重建。前端构建可用 `--check` 验证生成资源是否过期。
修改 OpenAPI 后从 `create_app().openapi()` 重新生成 `server/openapi.json`。
文档/契约反向测试在 `server/tests/test_documentation_contracts.py`，必须证明错误版本、缺少包文件、遗漏条件接收说明和失效链接会被拒绝。更新后重新生成开发者资产；不把历史文档重新混入接入包。事实来源与生成关系见维护手册。
涉及页面交互要在真实浏览器验证；模拟测试通过不代表手机收件或真实回调成功。

重构保持 `/bridge` API、旧 `/wechat` 反向代理别名、MCP 工具名、数据库文件名和密钥格式兼容。
生产发布先备份数据库及对应加密密钥，测试候选镜像，再切换；保留上一镜像与恢复步骤。
不要通过多 worker 扩容当前 SQLite 单进程实现。
