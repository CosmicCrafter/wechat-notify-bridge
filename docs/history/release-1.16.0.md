# 1.16.0 部署记录

2026-10-12 已部署重构版本。镜像 `wechat-notifier:1.16.0-refactor`，管理入口为 `/bridge/admin/`；旧 `/wechat` 入口保持兼容。

验证：
- 9 项版本、资源和生命周期针对性测试通过；完整重构回归见 refactor-validation.md。
- 禁用网络的候选容器使用线上数据库只读副本启动成功；账号、客户端、会话、任务卡片、OAuth 令牌和 Bot 数据保持一致。
- 公网新旧入口健康检查均返回 1.16.0；未认证管理请求返回 401。
- 公网管理页 app.js、style.css 与构建输入字节一致；开发者文档接口正常。
- 容器 healthy、重启次数 0；微信 connected / receiving；三个飞书 Bot 均启用且已配置。
- 未发送新的真实消息；保留的微信 -2 发送失败记录已与升级前备份核对，早于此次升级。

服务器保留数据与 secrets 完整备份，目录名 `before-refactor-1.16.0-20261012T135416Z`；旧容器 `wechat-notifier-before-1.16.0-refactor` 保留且禁止自动重启。不得在新旧容器之间并行启用微信接收。回滚前先停止新容器，恢复旧容器名称和 restart 策略。

本次没有更改 Nginx 路由、OAuth issuer 或既有运行环境变量。国内渠道继续直连，AI 回调保留既有代理配置。

## 同日管理流程调整

已发布页面镜像 `wechat-notifier:1.16.0-admin-flow`。代理页合并为 `#proxy`，节点在上、订阅在下，旧 hash 兼容跳转；密钥列表通过弹窗新增；新建微信 Bot 后自动开始扫码绑定，默认微信也复用 Bot 配置流程；手机会话登录移至独立入口。

本次仅更新管理页 HTML、JS、CSS。构建检查、浏览器弹窗错误反馈、合并页顺序、旧入口跳转及模拟微信扫码流程通过；未重新绑定真实微信。公网三份资源与本地字节一致，健康及未认证管理请求拒绝检查通过。备份 `before-admin-flow-1.16.0-20261012T140924Z`，回滚容器 `wechat-notifier-before-admin-flow`。

## Bot 弹窗调整

新增 Bot、微信配置和飞书配置均改为原生 dialog 弹窗，新增微信后在配置弹窗自动显示扫码流程。保留关闭、Esc、错误提示和既有保存接口。构建检查及隔离浏览器新增、扫码、飞书打开关闭、重名错误反馈通过；未改动真实绑定。

已发布镜像 `wechat-notifier:1.16.0-bot-dialog`，公网三份静态资源与本地完全一致，健康检查通过。备份 `before-bot-dialog-1.16.0-20261012T142548Z`，回滚容器 `wechat-notifier-before-bot-dialog`。

## 分步接入与权限弹窗

镜像 `wechat-notifier:1.16.0-bot-wizard` 已发布。新增平台选择、连接配置、飞书回调三步流程；Bot 授权改为弹窗；固定弹窗标题和操作区，统一字段与权限说明。浏览器隔离环境验证新增飞书、保存后进入回调页、复制地址、返回编辑、授权保存关闭；构建检查通过，线上三份静态资源逐字节一致、健康检查通过。未修改真实 Bot 凭据或授权。

备份 `before-bot-wizard-1.16.0-20261012T144154Z`，回滚容器 `wechat-notifier-before-bot-wizard`。


## Vue 3 + Element Plus 页面重构（2026-10-12）

管理中心、会话页、授权页改为 Vue 单文件组件；Bot 配置使用步骤条弹窗，密钥授权独立弹窗，节点和订阅合并。保留现有 API、数据、CSRF、Markdown 净化、消息幂等键与草稿隔离。

- 前端任务/草稿契约测试 3 项通过。
- 后端全量 303 项中，302 项直接通过；旧静态 HTML 文案断言改为 Vue 挂载入口后，绑定与 OAuth 定向 20 项通过。
- 浏览器隔离环境完成五类任务提交、前导零输入、草稿刷新恢复、发送、归档只读与恢复、Bot 向导、权限保存、代理与开发文档检查；未用真实审批做测试。
- 生产镜像 `wechat-notifier:1.16.0-elementplus`。备份 `/opt/wechat-notifier/backups/before-elementplus-1.16.0-20261012T150952Z`；回滚容器 `wechat-notifier-before-elementplus`。
- `/bridge` 和 `/wechat` 共 18 份静态资源哈希与本地一致；两个入口健康检查通过。
- 桌面浏览器和 390px 窄屏验证不等同于所有真实手机系统验收。现有 Node 构建工具只在开发/CI 使用，服务端继续运行 Python 静态资源。


## Bot 列表快捷操作（2026-10-12）

新增飞书回调地址复制和 Bot 删除确认。删除撤销关联 Key 授权、清除凭据并停止连接，保留历史消息；默认 Bot 使用删除标记防止重启重建及 bootstrap 恢复绑定。10 项 Bot 定向测试通过，线上按钮可见且复制提示成功。部署镜像 `wechat-notifier:1.16.0-bot-actions`；备份 `/opt/wechat-notifier/backups/before-bot-actions-1.16.0-20261012T152625Z`。未删除任何生产 Bot。
