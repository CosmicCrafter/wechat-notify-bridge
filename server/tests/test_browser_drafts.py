"""Exercise real browser storage semantics without adding a browser dependency."""
import shutil
import subprocess
from pathlib import Path
import pytest


def test_draft_reload_isolation_expiry_quota_and_logout():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required for the browser storage contract test')
    script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[1],'utf8');const data=new Map();let fail=false;
const storage={getItem:k=>data.get(k)||null,setItem:(k,v)=>{if(fail)throw Error('quota');data.set(k,v);},removeItem:k=>data.delete(k)};
function browser(){const ctx=vm.createContext({localStorage:storage,Date});vm.runInContext(source+';this.d=browserDrafts',ctx);return ctx.d;}
let a=browser();a.open('owner-A');a.set('reply:one',{text:'草稿',pending:{request_id:'same-stable-request',text:'草稿',attachment_ids:['uploaded-image']}});
let b=browser();b.open('owner-A');assert.equal(b.get('reply:one').pending.request_id,'same-stable-request');
b.set('task:two',{draft:{cid:'two',field_values:{date:'2026-10-04'}}});a.set('reply:one',{text:'更新'});
let c=browser();c.open('owner-A');assert.equal(c.get('task:two').draft.field_values.date,'2026-10-04');
c.open('owner-B');assert.equal(c.get('reply:one'),undefined);c.open('owner-A');
c.set('reply:one',null);assert.equal(c.get('reply:one'),undefined);
data.set(c.key,JSON.stringify({'old':{at:Date.now()-31*86400000,value:{text:'expired'}}}));
let e=browser();e.open('owner-A');assert.equal(e.get('old'),undefined);fail=true;e.set('reply:new',{text:'keep in memory'});assert.equal(e.failed,true);assert.equal(e.get('reply:new').text,'keep in memory');fail=false;e.set('reply:new',{text:'saved'});assert.equal(e.failed,false);e.clear();assert.equal(data.has('wechat-drafts-v1:owner-A'),false);
'''
    path = Path(__file__).parents[1]/'src/wechat_bridge/web/chat/drafts.js'
    subprocess.run([node, '-e', script, str(path)], check=True, capture_output=True, text=True)
