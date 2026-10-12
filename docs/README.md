# 文档索引

## 接手维护

- [维护手册](MAINTAINER.md)：架构、开发、验证、发布、备份与常见故障。
- [贡献指南](../CONTRIBUTING.md)：源码边界与变更步骤。
- [架构说明](architecture.md)：模块依赖和兼容约束。
- [安全说明](../SECURITY.md)：密钥、输入、权限和发布边界。
- [前端工程](../frontend/README.md)：Vue、Element Plus 与静态资源构建。

- [本次交付验证](handoff-validation.md)：检查结果与明确边界。

## 部署与使用

- [配置与数据存储](server/CONFIGURATION.md)：.env、运行目录、SQLite 与备份。

- [项目首页](../README.md)：服务器首次部署及本地运行。
- [服务器说明](../server/README.md)：配置、运行和 API。
- [多 Bot 与 Key](server/BOTS.md)、[飞书配置](server/FEISHU.md)。
- [手机会话](mobile-experience.md)、[任务卡片](server/TASK-CARDS.md)。

## 程序或 AI 接入

- [接入指南](integration/README.md)、[HTTP 接口](server/API.md)。
- [MCP 插件](../mcp-plugin/README.md)、[桌面唤醒](../mcp-plugin/DESKTOP-WAKE.md)。
- [投递可靠性](server/DELIVERY-RELIABILITY.md)、[宿主回调](server/MCP-EVENTS.md)。
- [微信 Markdown 排版](wechat-markdown/微信Markdown排版指南.md)。

`history/` 下的发布和历史验证记录用于追踪历史，不作为最新部署步骤；操作以当前首页、维护手册和源码为准。
