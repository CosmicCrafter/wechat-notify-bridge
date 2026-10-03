import sys
from pathlib import Path
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from desktop_relay import Queue, wake_prompt


def test_cursor_queue_restart_and_ambiguous_send(tmp_path):
    path=tmp_path/'queue.db'
    binding={'conversation_id':'c','thread_id':'t','app_tools_server':'app.mjs'}
    q=Queue(path,binding)
    q.capture({'events':[],'next_after_id':10})
    q.capture({'events':[{'id':12},{'id':15}],'next_after_id':15})
    assert q.pending()==[12,15]
    q.mark([12],'submitted')
    q.mark([15],'dispatching')
    q.db.close()
    q=Queue(path,binding)
    assert q.pending()==[]
    assert q.db.execute('SELECT status FROM events WHERE id=15').fetchone()[0]=='uncertain'
    q.capture({'events':[{'id':16}],'next_after_id':16})
    assert q.pending()==[]  # no retry or later-event reordering
    with pytest.raises(ValueError):
        q.capture({'events':[],'next_after_id':9})
    q.db.close()
    with pytest.raises(ValueError):
        Queue(path,dict(binding,thread_id='other'))


def test_payload_has_only_bound_identifiers():
    prompt=wake_prompt({'conversation_id':'cid','thread_id':'thread'},[20,23])
    assert 'conversation_id=cid' in prompt and 'after_id=19' in prompt
    assert 'limit=2' in prompt and 'wake-reply-20-23' in prompt
