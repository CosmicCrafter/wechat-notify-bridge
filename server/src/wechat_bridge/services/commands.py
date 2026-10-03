"""Owner-only slash commands. Never expose replies containing keys to MCP readers."""
from dataclasses import dataclass
import hashlib
import math

from wechat_bridge.storage.client_registry import ClientError

HELP = '''## 🧭 微信通知桥 · 使用帮助

**一个微信，接收通知、答复任务。**

**对话与状态**

- `/web` — 登录手机会话页，查看待办、完整记录并直接回复
- `/chats [页码]` — 查看聊天名称和回复标签
- `/status` — 查看连接与空闲心跳
- `/help` — 查看本说明

**管理客户端**

- `/getkey 名称` — 创建独立密钥，例如 `/getkey codex`
- `/list [页码]` — 查看客户端与最近调用
- `/resetkey 名称` — 重置密钥或重新启用，旧密钥立即失效
- `/revoke 名称` — 停用客户端
- `/rename 原名 新名` — 改名，密钥不变
- `/logout` — 退出所有手机会话页登录

**如何回复**

点击消息下方的“查看对话并回复”，无需手写标签。
也可以在微信发送 `[codex-名称] 内容`，准确标签见 `/chats`。

> 未带标签的微信消息留在公共收件箱。接入端已配置唤醒或回调时会自动处理，否则需要主动读取。

---
手机页支持 **待我处理、搜索、置顶和改名**；长按对话打开操作，草稿保存在当前浏览器。

名称支持 1–32 位中英文、数字、下划线和短横线，英文不区分大小写。密钥只填入对应客户端的私有配置。'''

ERRORS = {
    'invalid_client_name': '名称请使用 1–32 位中英文、数字、下划线或短横线。',
    'reserved_client_name': '这个名称由系统保留，请换一个名称。',
    'client_exists': '该名称已存在，原密钥未改变。忘记密钥请发送 /resetkey 名称。',
    'client_not_found': '未找到这个客户端，请发送 /list 查看名称。',
}


@dataclass
class Reply:
    text: str
    client_id: str | None = None
    issued_hash: str | None = None

    def __post_init__(self):
        if not self.text.startswith('## '):
            self.text = '## 微信通知桥\n\n' + self.text


def command_text(msg):
    items = msg.get('item_list', [])
    if len(items) != 1 or items[0].get('type') != 1 or items[0].get('ref_msg'):
        return None
    text = items[0].get('text_item', {}).get('text')
    return text.strip() if isinstance(text, str) and text.strip().startswith('/') else None


def format_time(value):
    if not value:
        return '未调用'
    # Explicit timezone, independent of the server container's local timezone.
    from datetime import datetime, timedelta, timezone
    beijing = timezone(timedelta(hours=8))
    return datetime.fromtimestamp(value, beijing).strftime('%Y-%m-%d %H:%M')


def issue_reply(result):
    client, key = result
    return Reply(f'## 客户端密钥\n\n**名称：{client["name"]}**\n\n密钥（40 位数字）：\n\n```text\n{key}\n```\n\n'
                 '复制到该客户端的 `api_key`，按文本保存。\n\n> 密钥只在创建或重置时显示；不要发给其他 AI。',
                 client['id'], hashlib.sha256(key.encode()).hexdigest())


def execute(store, text):
    """Called inside the same transaction as the incoming event and receive cursor."""
    parts = text.split()
    if not parts or len(text) > 300:
        return Reply('指令过长或格式不正确，请发送 /help 查看用法。')
    command, args = parts[0].lower(), parts[1:]
    registry = store.clients
    try:
        if command == '/help' and not args:
            return Reply(HELP)
        if command == '/web' and not args:
            from wechat_bridge.config import chat_url
            if not chat_url(): return Reply('尚未配置手机会话页地址，请在服务器设置 WECHAT_PUBLIC_BASE_URL。')
            code = store.portal.issue_code()
            return Reply(f'## 登录手机会话页\n\n**一次性登录码**\n\n```text\n{code}\n```\n\n'
                         '点击下方链接，输入登录码即可查看对话和回复。\n\n'
                         '> 10 分钟内有效，使用后失效。新登录码会替换旧码，请勿转发。\n\n'
                         '登录保留 30 天；发送 `/logout` 可退出所有设备。')
        if command == '/logout' and not args:
            store.db.execute('DELETE FROM web_sessions')
            store.set('web_login', {})
            return Reply('**已退出所有手机会话页登录。**\n\n再次登录请发送 `/web`。')
        if command == '/chats' and (not args or len(args) == 1 and args[0].isascii() and args[0].isdigit()):
            chats = store.conversations.list()
            page = int(args[0]) if args else 1
            pages = max(1, math.ceil(len(chats) / 5))
            if not 1 <= page <= pages: return Reply(f'页码范围为 1–{pages}。')
            if not chats: return Reply('还没有登记的聊天，请在 AI 客户端使用微信插件登记聊天名称。')
            from wechat_bridge.config import chat_url
            lines = [f'## 💬 聊天列表\n\n> 第 {page}/{pages} 页']
            for chat in chats[(page-1)*5:page*5]:
                link = chat_url(chat['id'])
                lines.append(f'- **{chat["caller"]} · {chat["name"]}**\n  `{chat["reply_tag"]}`' +
                             (f' · [进入对话]({link})' if link else ''))
            lines.append('---\n点击进入对话即可回复；也可在微信发送 `[标签] 内容`。\n\n> 是否自动处理取决于接入端的唤醒或回调配置。')
            return Reply('\n\n'.join(lines))
        if command == '/getkey' and len(args) == 1:
            return issue_reply(registry.create(args[0]))
        if command == '/resetkey' and len(args) == 1:
            return issue_reply(registry.rotate(registry.by_name(args[0])['id']))
        if command == '/revoke' and len(args) == 1:
            client = registry.revoke(registry.by_name(args[0])['id'])
            return Reply(f'**已停用 [{client["name"]}]**\n\n该密钥已失效。重新启用请发送 `/resetkey {client["name"]}`。')
        if command == '/rename' and len(args) == 2:
            client = registry.rename(registry.by_name(args[0])['id'], args[1])
            return Reply(f'**客户端已改名为 [{client["name"]}]**\n\n原密钥仍然有效。')
        if command == '/list' and (not args or len(args) == 1 and args[0].isascii() and args[0].isdigit()):
            clients = registry.list()
            page = int(args[0]) if args else 1
            pages = max(1, math.ceil(len(clients) / 10))
            if not 1 <= page <= pages:
                return Reply(f'页码范围为 1–{pages}，例如 /list 1。')
            if not clients:
                return Reply('还没有客户端。发送 /getkey codex 创建第一把密钥。')
            lines = [f'## 🔑 客户端列表\n\n> 第 {page}/{pages} 页']
            for client in clients[(page-1)*10:page*10]:
                lines.append(f'- **[{client["name"]}]** · {"启用" if client["enabled"] else "停用"}\n  最近调用：{format_time(client["last_seen_at"])}')
            lines.append('查看聊天：`/chats` · 使用帮助：`/help`\n\n> 列表不显示密钥。')
            return Reply('\n\n'.join(lines))
        if command == '/status' and not args:
            status = store.status()
            names = {'unbound':'未绑定','waiting_message':'等待首条消息','connected':'已连接',
                     'connecting':'连接中','retrying':'重连中','session_expired':'需重新绑定'}
            return Reply('## 📡 微信通知桥 · 状态\n\n**连接：' + names.get(status['connection_status'], '检查中') + '**\n\n' +
                         '- 最近收发：' + format_time(status['last_activity_at']) +
                         '\n- 最近微信发言：' + format_time(status['context_received_at']) +
                         '\n- 此后已推送：' + (str(status['accepted_sends_since_context']) + ' 条（接口接受）' if status['accepted_sends_since_context'] is not None else '尚无上下文记录') +
                         '\n- 下次空闲心跳：' + (format_time(status['next_heartbeat_at']) if status['next_heartbeat_at'] else '等待连接') +
                         ('\n\n**发送提示：** ' + status['send_recovery_hint'] if status['send_recovery_hint'] else '') +
                         ('\n\n**额度提示：** ' + status['quota_warning'] if status['quota_warning'] else '') +
                         '\n\n> 每次有效微信收发后顺延 12 小时，正常沟通时不发送心跳。\n\n聊天：`/chats` · 客户端：`/list` · 帮助：`/help`')
    except ClientError as exc:
        return Reply(ERRORS[exc.code])
    return Reply('未知指令或参数不正确。发送 /help 查看说明；例如 /getkey codex。')
