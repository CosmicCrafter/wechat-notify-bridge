"""Project shared task definitions into Feishu JSON 2.0 cards."""
from wechat_bridge.services.commands import format_time


def plain(value):
    return {'tag': 'plain_text', 'content': value}


def button(label, value=None, *, submit=False, url=None):
    item = dict(tag='button', text=plain(label), type='primary' if submit else 'default')
    if url:
        item['behaviors'] = [dict(type='open_url', default_url=url)]
    else:
        item['behaviors'] = [dict(type='callback', value=value)]
    if submit:
        item.update(action_type='form_submit', name='submit')
    return item


def card(text, label, link=None, task=None):
    excerpt = text[:5000] + ('…\n\n完整内容已保存，点击下方查看。' if len(text) > 5000 else '')
    elements = [dict(tag='markdown', content=excerpt)]
    title = label + ' 新消息'
    if task:
        title = label + ' ' + task['title']
        elements = [dict(tag='markdown', content=task['prompt'])]
        mode = task['mode']
        route = dict(conversation_id=task['conversation_id'], task_id=task['id'])
        if task['can_answer']:
            if mode == 'confirm':
                elements.extend(button(option['label'], dict(route, choice_id=option['id'])) for option in task['options'])
            if mode != 'confirm' or task['allow_custom']:
                fields = []
                if mode in ('single', 'multiple'):
                    fields.append(dict(tag='multi_select_static' if mode == 'multiple' else 'select_static',
                        name='choice_ids' if mode == 'multiple' else 'choice_id', placeholder=plain('请选择'),
                        options=[dict(text=plain(o['label']), value=o['id']) for o in task['options']]))
                    for option in task['options']:
                        if option['description']:
                            fields.append(dict(tag='markdown', content='**' + option['label'] + '**：' + option['description']))
                if mode == 'input' or task['allow_custom']:
                    fields.append(dict(tag='input', name='reply_text', placeholder=plain(task['input_hint'] or '输入回复'),
                                       max_length=2000, required=mode == 'input'))
                if mode == 'form':
                    for field in task['fields']:
                        fields.append(dict(tag='markdown', content=field['label'] + (' · 必填' if field['required'] else ' · 选填')))
                        item = dict(name='field_' + field['id'], required=field['required'])
                        if field['type'] == 'select':
                            item.update(tag='select_static', placeholder=plain('请选择'),
                                options=[dict(text=plain(o['label']), value=o['id']) for o in field['options']])
                        elif field['type'] == 'date':
                            item.update(tag='date_picker', placeholder=plain('选择日期'))
                        else:
                            item.update(tag='input', placeholder=plain(field['placeholder'] or '输入' + field['label']), max_length=1000)
                        fields.append(item)
                fields.append(button('提交回复', route, submit=True))
                elements.append(dict(tag='form', name='task_answer', elements=fields))
            elements.append(dict(tag='markdown', content='有效期至 ' + format_time(task['expires_at'])))
        else:
            state = {'answered':'已收到你的回复', 'processing':'处理中', 'completed':'已完成',
                     'cancelled':'已取消', 'expired':'已过期', 'pending':'会话已归档'}[task['status']]
            answer = task['answer'] or {}
            values = answer.get('choice_labels') or [answer.get('choice_label') or '']
            result = '、'.join(v for v in values if v)
            if answer.get('text'):
                result += '\n' + answer['text']
            elements.append(dict(tag='markdown', content='**' + state + '**\n' + result))
            if task['result']:
                elements.append(dict(tag='markdown', content=task['result']))
    if link:
        elements.append(button('查看完整对话 →', url=link))
    return dict(schema='2.0', config=dict(update_multi=True),
                header=dict(title=plain(title[:200]), template='blue'), body=dict(elements=elements))
