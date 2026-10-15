# 文档索引

源码候选：v1.18.0（未发布）；生产保护基线：v1.17.1 / 8e1c03b。REFINE-01 整理分支尚未部署；当前实例以实际运行版本及私有发布清单为准。

## 部署和维护中转站

从 [维护手册](MAINTAINER.md) 开始，随后阅读 [配置与数据](server/CONFIGURATION.md)、[管理员初始化与恢复](product-v3/OPERATIONS.md)、[首次部署](../README.md#快速部署与使用)。修改前查 [工程边界](architecture.md)、[贡献指南](../CONTRIBUTING.md)、[安全说明](../SECURITY.md)；前端源码和构建见 [前端工程](../frontend/README.md)。

## AI 接入已有站

按 [客户端安装](integration/CLIENT-SETUP.md) 选择 Codex / Claude Code 的插件或独立 MCP 路径，结合 [宿主说明](integration/AI-HOSTS.md)、[受保护收件](integration/RECEIVERS.md)。[插件说明](../mcp-plugin/README.md) 负责独立分发；自动唤醒另见 [桌面接收器](../mcp-plugin/DESKTOP-WAKE.md) 与 [事件订阅](server/MCP-EVENTS.md)，不把工具可用等同唤醒。

## 业务系统接入通知

从 [HTTP 接入](integration/HTTP.md) 和 [总指南](integration/README.md) 开始；字段与错误见 [API](server/API.md)，机器合同见 [OpenAPI](../server/openapi.json)。网站文档包不包含 MCP 程序或服务安装器，需按用途另取接入包或完整源码。

## 日常操作

[应用与连接授权](server/BOTS.md)、[飞书](server/FEISHU.md)、[新增飞书 Bot](server/新增飞书Bot操作指南.md)、[手机使用](mobile-experience.md)、[会话管理](mobile-conversations.md)、[任务卡片](server/TASK-CARDS.md)、[投递诊断](server/DELIVERY-RELIABILITY.md)、[微信排版](wechat-markdown/微信Markdown排版指南.md)。

## 历史与验收

[历史索引](history/README.md) 保留发布、设计和当时验收范围；[REFINE-01 交付](history/refine-01.md) 记录本次变更及未验证项。历史材料不属于当前部署步骤，也不默认进入接入包。
