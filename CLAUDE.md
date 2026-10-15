# Notify Bridge 工作入口

先读 AGENTS.md 的生产保护边界，再读 README.md 与 docs/MAINTAINER.md。当前源码为 v1.18.0 候选，未发布；REFINE-01 以生产稳定 v1.17.1 / 8e1c03b 为基线，在独立分支整理，未经部署验收不能称本分支已上线。管理认证、恢复及数据匹配见 docs/product-v3/OPERATIONS.md；历史迭代材料不作为当前操作步骤。

Notify Bridge 是统一消息中转站。你是站外开发、维护和使用助手，站内不运行通用 Agent。复用现有 Vue/FastAPI/SQLite/MCP 实现；不可仅为整理而重建框架、业务或历史。

独立测试使用 scripts/run_v03_test.py 的新数据、随机凭据和平台替身。真实服务部署、服务器认证/Bot 变更和 main 合并需要用户明确授权。测试替身、协议 SDK 验证、真人平台、新宿主和正式上线分别报告；不把读取或领取说成业务已执行，也不把快照生成说成恢复通过。

接入维护说明在 docs/integration/AI-HOSTS.md 与 HTTP.md。源码主维护位置、同步和打包命令在 MAINTAINER.md；不修改生成副本代替源码，不打印或提交真实密码、Key、验证码与加密主密钥。
