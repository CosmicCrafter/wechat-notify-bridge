# 手机图片回复

在手机会话页点击输入框旁的“＋”，展开附件面板后选择“相册”或“拍照”。选图后面板自动收起，图片在输入框上方预览。每条消息最多 3 张，支持不带文字发送。发送前可以预览和移除，发送后点击缩略图放大。图片草稿只保存在当前页面，关闭页面前会提示。

## 格式和存储

浏览器读取的单张文件最大 20 MiB，发送前缩小至最长边 2048 像素。服务端接受 JPEG、PNG、WebP，单张请求最多 5 MiB、解码前最多 800 万像素，不接受动画；重新编码为 JPEG 或 PNG，清除 EXIF 等元数据。HEIC 等能否导入取决于手机浏览器解码支持，不保证兼容，失败时可发送截图。

图片内容用现有 Fernet 密钥加密存储在 SQLite image_attachments 表。有效图片总量默认限 250 MiB，每会话最多 12 张待提交附件。未提交图片超过 24 小时，在服务启动或下次上传时清理。删除会话同时清理附件，归档会话仍可查看但不能上传或回复。数据库已释放的页供后续复用，文件不会立刻缩小；已有独立备份按原保留策略处理。

## API 和 MCP

- 手机上传：POST /chat/api/conversations/{cid}/images，body 为图片二进制，需要 owner session cookie、同源 Origin 和 X-Chat-Request: 1。
- 提交消息：POST /chat/api/conversations/{cid}/messages，JSON 包含 text（可空）、request_id、attachment_ids（最多3个）。相同 request_id 和内容重试不会重复入箱；已提交图片不能绑定另一条消息。
- 手机读图：GET /chat/api/conversations/{cid}/images/{image_id}，需要 owner cookie；未提交附件不可读取。
- AI 读图：GET /api/conversations/{conversation_id}/images/{image_id}，需该客户端 API/OAuth 身份，返回 MIME、尺寸及 base64。不提供公开附件链接。
- MCP getMessages 返回 attachments；调用新增 getImage(conversation_id,image_id)，返回原生 ImageContent，AI 才能看到图片内容。共享同一个客户端密钥的会话不构成独立安全边界。

已有桌面或云端唤醒通道按原规则处理图片消息；未订阅的会话不会自动开启唤醒。图片不刷新微信 context_token 或微信心跳计时。当前实现针对手机会话网页上传，不包括直接发送到 ClawBot 的原生微信图片下载。

## 部署和验证

反向代理请求体上限应至少 6 MiB，服务端单图仍限制 5 MiB。使用一个 worker，保持镜像内安装所需图片依赖；升级后刷新页面及宿主工具。

数据位置和备份见 [配置与运行数据](CONFIGURATION.md)。验收需要验证选图、预览、提交、取回图片和真人收件；相机支持及不同手机浏览器需单独检查。

历史测试记录见 [图片功能验收历史](../history/20261003-IMAGES.md)。
