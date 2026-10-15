# REFINE-01 工程与文档整理

基线：v1.17.1 / 8e1c03b。范围为独立分支 codex/refine-01 的 A → B → C，D 类可选重构暂缓。不是生产发布，不改变生产实例、main、通信目标或数据库结构。

## 批次与变更

- A：3edb240，修正管理员操作与有效维护入口、飞书引用回复提示、OpenAPI 条件接收头。31 项定向回归通过；只补契约描述，不放宽鉴权。
- B：a987d84，插件独立版本 1.11.0（旧 1.10.0 曾跨 12/18 工具复用）；统一安装源、用途白名单、公开版本指纹、HTTP 私有配置与身份检查；网站展示资料版本。24 项包/导出/示例回归、前端 7 项及三入口构建通过。
- C：bffdb5d，历史归位、有效链接/锚点、版本/工具/请求示例与五类交付包守卫；13 个反向场景及新 AI 验收。
- B/C 补充：按 2026-10-16 新授权加入匿名公开文档、公开/私有权限边界及生成产物检查；提交哈希见交付消息或 `git log -1 -- docs/history/refine-01.md`。不重做既有批次或扩展 D 类重构。

## 修改与移除范围

保留 Vue/FastAPI/SQLite、单进程、应用 Key/OAuth、protected 能力、旧 API 和迁移代码。源码变更涉及鉴权头的 OpenAPI 描述、飞书提示、开发者页面/导出元数据、客户端示例、公开静态文档路由和测试/打包检查；没有重做通信或存储架构。

旧 docs/handoff-validation.md 归位到 [2026-10-13 历史交付](20261013-handoff-validation.md)。v0.2 原型、v0.3/F02 原始设计、历史发布与验收仍保留；阶段日志加历史状态标记。开发者包不再收录旧原型、历史验收或整份部署首页；旧账号 Key 登录/自动猜输入任务等失效操作说明已移除或更新，正常轮换与旧兼容重置分开解释。

完整文件清单以 `git diff --name-status 8e1c03b..HEAD` 和各批次的 `git show --stat` 为准；生成副本由源文件重建，不另行编辑。

## 验证与待确认

验证日期：2026-10-15（Asia/Singapore）。

| 检查 | 结果与边界 |
|---|---|
| 自动回归 | PASS：406 项全量；后续指纹/守卫与文档完善后 33 项定向复测通过，两组不相加。既有 Starlette/AnyIO 弃用提示 1 项 |
| 前端 | PASS：Vue 三入口构建、7 项契约、Prettier；C 批没有新增 UI 代码 |
| 工程与包 | PASS：100 个 Python 文件 Ruff 格式检查、pip check、check_project；源码 ZIP 独立解压后检查、干净 wheel 构建与资源核验 |
| 反向保护 | PASS：错误版本/清单版本、缺少接收头或解释、对 legacy 强制头、缺必需文件、失效链接/锚点、错误指纹范围及新旧格式公开凭据样式均被拒绝 |
| 网站内容与下载 | PASS：真实隔离 API 返回的网站七类正文与下载资料，版本/来源与生成源对应；不是登录后逐屏 UI 验收 |
| 无历史新 AI | PASS：仅给下载资料与网站正文，实际 prepare 安装锁定依赖、生成三份宿主配置；HTTP identity-only 和固定键 dry_run 成功。只注册逻辑会话、不真实外发 |
| 真正 Codex CLI | PASS：0.162.0-alpha.17.2，全新 thread 01a1402b-bf62-7200-8e76-180c806483ff；按包内生成配置加载 MCP，7 次调用完成身份/登记/dry_run/替身发送/回执/历史/收件，续接 2 次准确读到管理 API 回传。应用 cd0ff18c31ad434ab0a71df24b55a945，会话 b6e822db3d744f8bb35afdefba8ad396，模拟出站历史 1、入站 1/历史 2、source=admin；全局配置摘要未变 |
| 首次 CLI 文件读取 | BLOCKED：宿主执行策略连只读 shell 也拒绝；原始结果保留，未扩大权限。安装由无历史新 AI 完成，之后 CLI 仅用真实 MCP 验证，通过结果不覆盖这条受阻记录 |
| 浏览器人工体验 | 待确认：按用户要求，稍后与审查员确认；未记 PASS，未绕过管理登录 |
| Claude / Work / Dot / 自动唤醒 | UNVERIFIED：Claude 配置能解析不等于真实 Claude 宿主通过；本轮无自动事件唤醒、聊天强身份或真人微信/飞书收件验收 |
| 远端 CI | UNVERIFIED：现有 Windows/Linux 工作流已扩展，本轮不推送，因此没有新远端 CI 运行证据 |

新 AI 首次指出文档包与 MCP/HTTP 包指纹不同却缺少范围说明，已补 fingerprint_scope、用途说明和错误范围反向测试；它仅依据最终资料复核通过，并比较 11 个公开运行/依赖文件逐字节不变，未重复安装或读取凭据。初轮“重复 ZIP 成员”测试仍使用已退出包的根 README，已改为实际收录文件后验证拒绝，未放松检查。

CLI 使用按次隔离配置及 --ignore-user-config / --ignore-rules，参考[官方 CLI 说明](https://learn.chatgpt.com/docs/cli/reference)。本轮默认 legacy 接入证明包的真实工具链可用；protected/旧 Key/OAuth/F02 分流由定向和全量回归覆盖，不扩大为新宿主强身份验证。

原始无凭据结果在本机忽略目录 `.private/refine-01-test/`：fresh-reader/acceptance-reader.json、acceptance-summary.json、mcp*.result.json/jsonl、mcp-proof.json。含私有配置的原始下载包只留该受保护目录，不纳入 Git 或公开报告。

本轮不部署、不推送、不合并 main；候选版本不替换生产 v1.17.1。未触及生产库，无数据迁移；撤销本轮候选代码不需要恢复生产数据。

## 本地验收与回退

新增公开文档候选入口为 http://127.0.0.1:19869/docs/，无需登录。该进程使用独立 `.private/refine-01-public/`、随机账号和替身平台，仅监听回环，禁用接收 worker。测试配置目录 ACL 限当前 Windows 用户与 SYSTEM；账号不在本文展示。旧 19865 和 19868 预览均保留，19868 后端未重启，新增公开路由请在 19869 验收；未安装自启动服务。

此前管理端人工验收入口为 http://127.0.0.1:19868/admin/#help，账号仅在 `.private/refine-01-test/local-access.json`。本次匿名验收不需要读取该账号，也不替代用户稍后与审查员进行的私有管理端体验确认。正式网站仍是旧稳定基线，不因本地生成资产而更新。

最终源码/独立插件 ZIP、wheel 和 SHA256 清单保存在 `.private/refine-01-test/release/`；AI/HTTP 已配置验收包在 final-reader/，属于私有包。安装流程对应当前代码，不需要生产权限。

以上为前三批的历史交付包；加入公开文档后的源码 ZIP、wheel 与 SHA256 清单另存 `.private/refine-01-public/release/`，不覆盖旧验收证据。

本轮没有数据库迁移、生产写入或依赖升级。候选修改由 A/B/C 及本次补充提交隔离；如不采用，保留本分支即可，生产无需回退。不覆盖用户工作区或用全局 reset/clean 撤销。

## B/C 补充：匿名公开开发文档

验证日期：2026-10-16（Asia/Singapore）。服务版本仍为 1.17.1，插件候选版本仍为 1.11.0；本分支尚未正式发布。

稳定路由为部署基址后的 `/docs/`；包含 HTTP、MCP、会话接收协议、示例、错误说明、任务及投递重试。可直接读取 `/docs/index.md`、`/docs/integration/HTTP.md`、`/docs/integration/CLIENT-SETUP.md`、`/docs/integration/RECEIVERS.md`、`/docs/openapi.json` 和 `/docs/download.zip`。此处仅为候选路由契约，未宣称正式域名已部署。

维护关系沿用 `docs/integration`、`docs/server`、`server/openapi.json` 和标准库 Python 示例。现有 `build_developer_kit.py` 从用途白名单同时生成后台正文、通用文档 ZIP 与公开 HTML/Markdown；构建时复用锁定的 marked 和共享主题，不增加依赖、前端应用、CDN 或运行时脚本。`--check` 验证输入及输出摘要，交付源码无需安装 Node 即可检查既有产物。

匿名路由只读取固定构建资产，不访问 Store，不生成实例配置。旧 `/openapi.json`、后台帮助 API、应用/Key/消息 API、含实例配置的导出接口仍保持原鉴权。公开下载只包含 19 个通用成员，无 DEPLOYMENT.json、CONNECTION.json、真实 Key 或历史验收材料；公开规范中的受保护操作仍声明 Bearer，并保留 protected 会话条件接收头。

| 检查 | 结果与边界 |
|---|---|
| 匿名真实浏览器 | PASS：新端口无登录会话，登录页公开链接、网页正文、HTTP/MCP/会话导航、最终 ZIP 下载可用；桌面和 390px 窄屏实际查看，表格在容器内横向滚动 |
| 实际下载 | PASS：浏览器下载包与最终生成包逐字节一致；19 个成员，SHA256 `0e49a1ddbc3d164f83bf9d4da291063f95708859b29a4a5ab5876b3b79a6231f` |
| 无历史新 AI | PASS：仅给公开 URL，无仓库、记忆、Cookie、Authorization 或私有配置；34 个内部目标均 200，ZIP 的 30 条相对链接有效；下载示例 `--help` 成功，未尝试网络连接 |
| 权限边界 | PASS：匿名后台应用/帮助/下载、收件箱、旧 OpenAPI 均 401；私有包 POST 也拒绝，文档路径穿越和私有文件猜测拒绝；自动测试确认无数据库写入 |
| 源码和包一致性 | PASS：网页、后台 RELEASE 指纹一致，公开 OpenAPI 与源文件逐字节一致；六类资料检查通过；缺版本、接收说明、Bearer、必需文件、有效链接及产物摘要的反向场景均拒绝 |
| 定向回归 | PASS：53 项包/导出/示例/公开文档回归；随后补充 Bearer 与挂载前缀测试后 22 项定向复测通过，两组不相加 |
| 最终全量回归 | PASS：最终独立执行 421 passed，592.79 秒；既有 Starlette/AnyIO 弃用提示 1 项，无失败 |
| 前端与格式 | PASS：三入口构建、7 项前端测试、Prettier、101 个 Python 生产/构建文件 Ruff 格式检查；未升级依赖 |
| wheel 运行 | PASS：干净构建、临时解压后从 wheel 路径实际加载，四个公开入口均 200；禁止外部连接且无外部连接尝试，无数据库初始化 |
| 最终源码交付 | PASS：源码 ZIP 的 327 个文件在独立临时目录解压并运行全部工程/资料检查，无原仓库与 node_modules 依赖 |
| 正式域名与真人通信 | UNVERIFIED：没有部署、连接生产 Bot 或复测真人收发；本次静态文档与权限结果不扩展为真实宿主自动唤醒、Claude 或 Work/Dot 通过 |

新 AI 首轮发现三篇规范仍用客户端包内的 F02-RECEIVERS.md 文件名，公开站和源码包实际为 RECEIVERS.md。已在权威 Markdown 改为可点击的本地协议链接，原有 MCP/HTTP 包由构建器映射回兼容文件名；最终网页、Markdown 和 ZIP 均复核通过。保留首轮问题记录，没有用修改副本或放松链接检查掩盖问题。

一次较早全量测试与文档修正并行，远程包构建器已加载旧模块，出现 418 PASS / 1 FAIL（协议链接文件名）；未计为通过。修正后的新进程定向回归已通过，最终完整复测结果按上表另记。

原始证据留在忽略目录 `.private/refine-01-public/`：`anonymous-final.json`、`wheel-check.json`、`reader/`（含初轮发现及 `recheck-20261015T160147Z/final-recheck-result.json`）。公开资料不收录这些环境证据或任何私有配置。

## RELEASE-PREP：1.18.0 候选收尾

日期：2026-10-16（Asia/Singapore），起点 86ead62。复用用户提供的独立审核结论：P1 发布前独立服务版本、P2 MCP 实际地址/纯飞书登录、P3 接入应用名称。只处理这些定点项，搜索/复制和 D 类重构不实施。

服务、前端、锁文件根元数据、OpenAPI 及生成资料升级为 **1.18.0 候选**；插件保留 **1.11.0**。新增匿名路由是向后兼容扩展，现有版本规则无冲突。README/维护入口明确候选与生产保护基线 v1.17.1/8e1c03b 分开；未创建发布或移动标签。

README、远程 MCP 指南和插件说明统一要求使用导出的 mcp_url，固定 /bridge/mcp 只作为新部署示例；纯飞书在“系统设置→手机端登录”取码。网站 OAuth 登录及失效码提示同步，授权提示区分正常 Key 轮换和 OAuth 撤销。当前菜单统一“接入应用”，Key 仍是应用凭据。增加前端锁文件版本校验及菜单/地址/纯飞书入口的 3 个反向场景；真实产物测试改从服务版本源读取，不重复硬编码每轮版本。

| 项目 | 本批结果与边界 |
|---|---|
| Windows Python 完整回归 | PASS：Python 3.12.3 / Node 20.19.6；424 passed / 1 既有弃用警告，598.97 秒；不是远端托管运行 |
| Linux 隔离流水线 | PASS：Python 3.12.15、Node 20，424 passed / 1 既有弃用警告，131.46 秒；离线 npm ci、前端构建/7 测试/格式、Ruff、pip check、project check、wheel、源码/解压校验、本机/远程插件均通过 |
| 本机前端/工程 | PASS：三入口构建、7 项测试、Prettier、101 Python 文件格式、pip check、六类资料与 OpenAPI/版本一致性检查；Windows wheel 干净构建并从解压路径实际加载，公开入口与版本正确、无外部请求 |
| 匿名真实 HTTP | PASS：15 个公开/私有边界检查；公开 HTML/MD/OpenAPI/ZIP 200、私有数据/账号/Key/消息及配置包 POST 拒绝；no-store、无 Set-Cookie，公开包 19 成员且无 DEPLOYMENT |
| 本轮独立浏览器 | BLOCKED：浏览器工具两次无法加载请求头策略，未绕过；本轮不记浏览器 PASS。86ead62 的旧浏览器通过保留为历史，不能扩大为 1.18.0 的本次验证 |
| 无历史新 AI | PASS：公开文档 + 本次隔离应用包；HTTP identity-only/默认 dry_run，实际 stdio MCP initialize/list 18 tools/身份/登记/dry_run。未外发、未读出私有配置、未改全局设置；不是新的 Codex/Claude 完整宿主或自动唤醒验收 |
| Nginx 前缀与缓存 | PASS：原 nginx.conf 模板在无外网/无公开端口的独立临时容器中，/bridge/docs 相对跳转和 12 个 GET、私有 401/路径 404、no-store、旧 /wechat 别名均通过；容器已清理，未改正式代理 |
| GitHub 托管 Linux/Windows CI | 提交前 UNVERIFIED：本地两种系统的同套检查不等于托管 CI；未将旧提交的 CI 当作本提交通过。后续托管结果以交付消息和精确提交的运行记录为准 |
| 正式域名、TLS/CDN、真人通信 | UNVERIFIED：未访问生产、未切回调、未部署；发布清单见 [1.18.0 候选说明](release-1.18.0.md) |

Linux 完整测试读取固定公开源码副本，断网运行、不挂载生产或主工作区；后续仅补前端 README 菜单文案及本交付记录，代码和生成资产无再变更。首次临时代理检查未等后端就绪出现 502；就绪等待后原模板全部通过，属于准备脚本时序，未修改产品去规避校验。

依赖告警另记：npm audit 报 3 项 high，沿 unplugin-vue-components → chokidar → braces，实际 npm ls --omit=dev 不含这条链；[上游公告](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm)记录深嵌套模式导致 Node 栈耗尽。它属于现有构建工具依赖，Python 服务和静态页面不运行该 Node 工具；这不构成“已证明无风险”。本批未升级依赖，正式发布前应单独决定构建依赖处置，不能用 npm audit fix --force 顺带大版本升级。Windows 本机 registry 的 audit API 返回空错误，Linux 官方 registry 查询成功，未把前者记安全通过。

测试原记录和制品在本机受保护忽略目录 `.private/release-prep/`：windows-junit.xml、linux-results/、anonymous-http.json、proxy/result.json、fresh-reader/release-prep-fresh-reader-result.json、release/。它们不进入仓库或匿名文档。19869 仅重载隔离测试进程至 1.18.0，保留测试数据和随机账号；没有生产操作或数据库迁移。旧审查 ZIP 保持 86ead62，不覆盖成另一候选。

本批当前源码变更清单可用 `git show --stat` 和 `git diff --name-status 86ead62..HEAD`；发布步骤与恢复边界见候选发布说明。正式上线授权前停止。

## 完整文件清单

下表相对于生产代码基线 8e1c03b；M=修改、A=新增、R=归位。历史原件未永久删除，唯一移除的原路径由 R 行明确列出。生成产物的内容收缩不等于删除仓库历史。

| 类型 | 路径 |
|---|---|
| M | `.github/workflows/test.yml` |
| M | `AGENTS.md` |
| M | `CLAUDE.md` |
| M | `CONTRIBUTING.md` |
| M | `README.md` |
| M | `docs/MAINTAINER.md` |
| M | `docs/README.md` |
| M | `docs/architecture.md` |
| M | `docs/f02/DELIVERY.md` |
| M | `docs/f02/IMPLEMENTATION.md` |
| R100 | `docs/handoff-validation.md` → `docs/history/20261013-handoff-validation.md` |
| M | `docs/history/README.md` |
| A | `docs/history/refine-01.md` |
| A | `docs/history/release-1.18.0.md` |
| M | `docs/integration/AI-HOSTS.md` |
| M | `docs/integration/CLIENT-SETUP.md` |
| M | `docs/integration/HTTP.md` |
| M | `docs/integration/README.md` |
| M | `docs/integration/RECEIVERS.md` |
| M | `docs/mobile-conversations.md` |
| M | `docs/mobile-experience.md` |
| M | `docs/product-v2/README.md` |
| M | `docs/product-v2/工作稿.md` |
| M | `docs/product-v3/IMPLEMENTATION.md` |
| M | `docs/server/API.md` |
| M | `docs/server/BOTS.md` |
| M | `docs/server/CHAT.md` |
| M | `docs/server/COMMANDS.md` |
| M | `docs/server/FEISHU.md` |
| M | `docs/server/MCP-EVENTS.md` |
| M | `docs/server/REMOTE-MCP.md` |
| M | `docs/server/TASK-CARDS.md` |
| M | `docs/server/新增飞书Bot操作指南.md` |
| M | `examples/python/notify_bridge.py` |
| M | `frontend/README.md` |
| M | `frontend/build-manifest.json` |
| M | `frontend/package-lock.json` |
| M | `frontend/package.json` |
| A | `frontend/render-docs.mjs` |
| M | `frontend/src/admin/components/Login.vue` |
| M | `frontend/src/admin/pages/Developer.vue` |
| M | `frontend/src/chat/errors.js` |
| M | `frontend/src/oauth/App.vue` |
| M | `mcp-plugin/.codex-plugin/plugin.json` |
| M | `mcp-plugin/README.md` |
| M | `mcp-plugin/examples/client.json` |
| M | `mcp-plugin/plugin.json` |
| M | `mcp-plugin/skills/wechat-notify/SKILL.md` |
| M | `mcp-plugin/skills/wechat-notify/references/channels.md` |
| M | `mcp-plugin/tests/test_packages.py` |
| M | `mcp-plugin/tools/build_local_plugin.py` |
| M | `mcp-plugin/tools/build_remote_plugin.py` |
| M | `mcp-plugin/tools/package_checks.py` |
| M | `scripts/build_release.py` |
| A | `scripts/check_documentation.py` |
| M | `scripts/check_project.py` |
| M | `scripts/run_v03_test.py` |
| M | `server/README.md` |
| M | `server/openapi.json` |
| M | `server/pyproject.toml` |
| M | `server/scripts/build_developer_kit.py` |
| M | `server/scripts/build_onboarding_assets.py` |
| M | `server/src/wechat_bridge/__init__.py` |
| A | `server/src/wechat_bridge/api/documentation.py` |
| M | `server/src/wechat_bridge/api/security.py` |
| M | `server/src/wechat_bridge/app.py` |
| M | `server/src/wechat_bridge/channels/feishu/cards.py` |
| M | `server/src/wechat_bridge/services/onboarding.py` |
| M | `server/src/wechat_bridge/web/admin/app.js` |
| M | `server/src/wechat_bridge/web/admin/developer-docs.json` |
| M | `server/src/wechat_bridge/web/admin/developer-kit.zip` |
| M | `server/src/wechat_bridge/web/admin/onboarding-template.zip` |
| A | `server/src/wechat_bridge/web/admin/public-docs.zip` |
| M | `server/src/wechat_bridge/web/admin/style.css` |
| M | `server/src/wechat_bridge/web/chat/app.js` |
| M | `server/src/wechat_bridge/web/oauth/app.js` |
| M | `server/tests/test_developer_build.py` |
| A | `server/tests/test_documentation_contracts.py` |
| M | `server/tests/test_f02_inbound.py` |
| A | `server/tests/test_http_example.py` |
| M | `server/tests/test_package.py` |
| A | `server/tests/test_public_docs.py` |
