# REFINE-01 工程与文档整理

基线：v1.17.1 / 8e1c03b。范围为独立分支 codex/refine-01 的 A → B → C，D 类可选重构暂缓。不是生产发布，不改变生产实例、main、通信目标或数据库结构。

## 批次与变更

- A：3edb240，修正管理员操作与有效维护入口、飞书引用回复提示、OpenAPI 条件接收头。31 项定向回归通过；只补契约描述，不放宽鉴权。
- B：a987d84，插件独立版本 1.11.0（旧 1.10.0 曾跨 12/18 工具复用）；统一安装源、用途白名单、公开版本指纹、HTTP 私有配置与身份检查；网站展示资料版本。24 项包/导出/示例回归、前端 7 项及三入口构建通过。
- C：历史归位、有效链接/锚点、版本/工具/请求示例与五类交付包守卫；13 个反向场景及新 AI 验收。提交与本文件同批，精确哈希见交付消息或 `git log -1 -- docs/history/refine-01.md`。

## 修改与移除范围

保留 Vue/FastAPI/SQLite、单进程、应用 Key/OAuth、protected 能力、旧 API 和迁移代码。源码变更仅涉及鉴权头的 OpenAPI 描述、飞书提示、开发者页面/导出元数据、客户端示例和测试/打包检查；没有重做通信或存储架构。

旧 docs/handoff-validation.md 归位到 [2026-10-13 历史交付](20261013-handoff-validation.md)。v0.2 原型、v0.3/F02 原始设计、历史发布与验收仍保留；阶段日志加历史状态标记。开发者包不再收录旧原型、历史验收或整份部署首页；旧账号 Key 登录/自动猜输入任务等失效操作说明已移除或更新，正常轮换与旧兼容重置分开解释。

完整文件清单以 `git diff --name-status 8e1c03b..HEAD` 和三个批次的 `git show --stat` 为准；生成副本由源文件重建，不另行编辑。

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

入口为 http://127.0.0.1:19868/admin/#help，独立数据、随机账号、替身平台。账号只在 `.private/refine-01-test/local-access.json`；真实 Key/密码不在本文展示。原 19865 预览未停止；19868 只是当前验收进程，未安装自启动服务。正式网站仍是旧稳定基线，不因本地生成资产而更新。

最终源码/独立插件 ZIP、wheel 和 SHA256 清单保存在 `.private/refine-01-test/release/`；AI/HTTP 已配置验收包在 final-reader/，属于私有包。安装流程对应当前代码，不需要生产权限。

本轮没有数据库迁移、生产写入或依赖升级。候选修改由 A/B/C 三个提交隔离；如不采用，保留本分支即可，生产无需回退。不覆盖用户工作区或用全局 reset/clean 撤销。

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
| M | `frontend/build-manifest.json` |
| M | `frontend/src/admin/pages/Developer.vue` |
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
| A | `scripts/check_documentation.py` |
| M | `scripts/check_project.py` |
| M | `scripts/run_v03_test.py` |
| M | `server/README.md` |
| M | `server/openapi.json` |
| M | `server/scripts/build_developer_kit.py` |
| M | `server/scripts/build_onboarding_assets.py` |
| M | `server/src/wechat_bridge/api/security.py` |
| M | `server/src/wechat_bridge/channels/feishu/cards.py` |
| M | `server/src/wechat_bridge/services/onboarding.py` |
| M | `server/src/wechat_bridge/web/admin/app.js` |
| M | `server/src/wechat_bridge/web/admin/developer-docs.json` |
| M | `server/src/wechat_bridge/web/admin/developer-kit.zip` |
| M | `server/src/wechat_bridge/web/admin/onboarding-template.zip` |
| M | `server/src/wechat_bridge/web/admin/style.css` |
| M | `server/tests/test_developer_build.py` |
| A | `server/tests/test_documentation_contracts.py` |
| M | `server/tests/test_f02_inbound.py` |
| A | `server/tests/test_http_example.py` |
| M | `server/tests/test_package.py` |
