# 插件 1.5.0 设计依据与验证

核对日期：2026-10-03。插件身份及已有工具名保持稳定；本次调整说明、Schema、错误处理和发布包，不增加任意收件人、自动轮询或新的唤醒机制。

## 采用的规范

| 官方来源 | 采用内容 | 本项目落实 |
| --- | --- | --- |
| [Agent Skills specification](https://agentskills.io/specification) | SKILL.md 元数据、相对引用和按需加载 | 主文件保留共同流程，收件、路由、恢复、接入和排版参考按场景读取 |
| [OpenAI Build skills](https://learn.chatgpt.com/docs/build-skills) | 明确触发范围，UI 元数据，工作流验证 | 精简 description，保留微信通知名称与自动发现默认行为 |
| [OpenAI Package your plugin](https://developers.openai.com/plugins/build/plugins) | 可移植包、兼容清单和 MCP 配置 | 保留 plugin.json / mcp.json，同步 .codex-plugin 与 .mcp.json；发布目录匹配插件身份 |
| [MCP Tools 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) | 输入 Schema、工具执行错误、图像结果 | 保持现用 SDK/协议兼容，参数约束可发现，失败通过 SDK isError，图片保持原生 ImageContent |
| [MCP ToolAnnotations](https://modelcontextprotocol.io/specification/2025-11-25/schema#toolannotations) | 标注真实副作用与重复调用语义 | getMessages 明确修改已读状态；发送按原去重参数幂等，归档/恢复不发微信 |

不因新文档存在就升级协议或 SDK。现有 MCP Events 适配层保持原状；这次不宣称完整实现其他协议版本。

## 结构与错误边界

Skill 的入口提供默认流程，references 仅在当前模式需要时加载；安装操作放在插件 README，不让普通发送加载部署说明。主清单保留原 defaultPrompt；没有为本次优化新增可选品牌字段。

本机和远程 MCP 共用工具定义与错误分类。API 错误只透出白名单代码和固定建议，不转发响应正文、URL、令牌或验证错误中的原始输入。读取失败不再称作“发送未确认”；发送失败提醒查询原会话与去重键，不自动重试。

输入 Schema 增加既有 API 范围约束，工具名称和可选参数默认值保持兼容。getMessages 的注解变化可能让宿主显示写操作提示，这是对既有已读副作用的纠正，不是新增读消息权限。

## 场景验收

| 场景 | 应观察到的行为 |
| --- | --- |
| 只查服务状态 | 查询身份，不登记会话、不发测试消息 |
| 两个聊天共用客户端 | 分别保存稳定会话 ID；交错调用不串路由 |
| 图片消息没有文字 | 读取附件实际图像，不忽略消息或只看元数据 |
| 发送超时 | 不重试、不换键；提示查询原回执 |
| 恢复归档发生同名冲突 | 错误可区分，不切换 ID、不擅自归档其他任务 |
| 401 或服务返回恶意正文 | 提示重连或固定错误，不向模型透出正文中的凭据/指令 |
| 读取一条待处理回复 | 手机记录变为 client_read，但不宣称任务完成 |
| 本机/远程插件包 | 单根目录、身份版本一致，Skill 参考齐全，配置对应正确传输 |

自动化测试覆盖工具 Schema、传输、错误和既有后端行为；静态 Skill 校验只证明结构有效。上述模型决策要求还需真实宿主使用反馈，不能用关键词匹配测试冒充独立模型行为验证。
