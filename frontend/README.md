# 前端工程

采用 Vue 3、Element Plus 和 Vite。管理页、手机会话页、OAuth 授权页使用独立入口，共享主题、日期格式与经过净化的 Markdown 组件。

## 目录

- `src/admin/`：管理布局、Bot 三步配置向导、接入应用与 Key、权限弹窗、代理与开发者文档。
- `src/chat/`：会话、草稿、附件、手势和任务卡片。
- `src/oauth/`：登录与授权确认。
- `src/shared/`：视觉变量、Markdown、安全错误提示和时间格式。
- `tests/`：任务答复与草稿隔离的契约测试。
- `docs/`：DOC-01 已确认视觉的首页模板、导航元数据、CSS 和渐进增强脚本；文章正文不在这里另存一份。
- `render-docs.mjs`：用现有 marked 静态渲染同源 Markdown、正文目录和全文搜索索引，不启动另一套文档前端。

## 构建

开发环境需 Node.js 20.19+ 或 22.12+。在本目录运行 `npm ci`、`npm test`、`npm run build`。
项目根目录可运行 `python scripts/build_frontend.py --check` 检查源码与产物哈希。文本输入按 LF 规范化后计算哈希，避免 Git 跨平台换行转换误报；二进制输入及构建产物仍按原始字节校验。
产物写入 `server/src/wechat_bridge/web/{admin,chat,oauth}/`，随 Python 包部署，服务器不需要 Node.js。
依赖通过锁文件固定、按组件构建，全部同源提供，不使用 CDN。每个入口独立加载；没有宣称任务组件按网络分包懒加载。

公开文档的生成命令在仓库根目录执行 `python server/scripts/build_developer_kit.py`。它同时更新网页资源、后台开发者正文和通用文档包；`--check` 只验证来源/产物摘要，不修复文件，也不要求 Node。`llms.txt` 按同一导航和 Markdown 集合自动生成。修改 Markdown、docs 展示输入或生成器后须重新生成，不能直接编辑 public-docs.zip。

`npm run format:check` 覆盖 docs 下的展示源；项目一致性检查校验其输入摘要、链接、版本、搜索集合和公开文件边界。站点使用既有 CSP 的同源脚本权限，不启用 unsafe-inline；禁用脚本仍可读正文和静态导航。

新增页面须复用组件及主题，保持认证、CSRF、幂等请求和草稿隔离契约。禁止在构建产物中直接修改业务逻辑。
旧原生页面辅助资源已移除；升级后应刷新旧页面。业务 API 和旧 /wechat 入口仍保持兼容。

参考：[Element Plus](https://element-plus.org/en-US/guide/quickstart.html)、[Vue](https://vuejs.org/guide/quick-start)。
