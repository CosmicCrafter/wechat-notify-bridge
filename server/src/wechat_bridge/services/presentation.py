"""WeChat-only presentation. Canonical bodies and delivery fingerprints stay unchanged."""
from wechat_bridge.services.commands import format_time


def present(text, kind, task=None, due=None):
    if task:
        mode = task.get('mode', 'single')
        names = {'single': '单选', 'multiple': '多选', 'confirm': '快捷确认', 'input': '填写回复', 'form': '填写表单'}
        lines = ['## 📋 ' + task['title'], '> ' + names[mode] + ' · 等待你的答复', task['prompt']]
        for option in task['options']:
            lines.append('- **' + option['label'] + '**' + (' · 推荐' if option['recommended'] else '') +
                         ('\n  ' + option['description'] if option['description'] else ''))
        for field in task.get('fields', []):
            lines.append('- **' + field['label'] + '** · ' + ('必填' if field['required'] else '选填'))
        if mode == 'multiple':
            lines.append('可选 **' + str(task['min_choices']) + '–' + str(task['max_choices']) + ' 项**。')
        if task['allow_custom'] and mode not in ('input', 'form'):
            lines.append('也可以填写自己的安排。')
        if due:
            lines.append('---\n有效期至 ' + format_time(due))
        return '\n\n'.join(lines)
    if kind == 'notification':
        # Only structured notices use this canonical template. Raw sendMessage stays verbatim.
        return text.replace('## 通知 · ', '## ℹ️ ').replace('## 需要处理 · ', '## ⚠️ ').replace('## 紧急提醒 · ', '## 🔴 ').replace(
            '\n\n**当前情况**\n\n', '\n\n**发生了什么**\n\n').replace('\n\n**需要你处理**\n\n', '\n\n---\n\n**需要你的帮助**\n\n')
    return text
