'use strict';
const $ = id => document.getElementById(id);
const state = {cid:new URL(location.href).searchParams.get('c'), anchor:Number(new URL(location.href).searchParams.get('m'))||0, messages:new Map(), chats:[], generation:0, authenticated:false, busy:false, polling:false, hasNewer:false, drafts:new Map(), pending:new Map()};
const imageDrafts = new Map();
let taskList=[],taskCursor=null,taskListGeneration=0,searchTimer;
let tasksReady=false,tasksLoading=false,tasksFailed=false;
function loadTaskAssets(){
  if(tasksReady||tasksLoading||tasksFailed)return;tasksLoading=true;
  if(!document.getElementById('task-style')){const css=el('link');css.id='task-style';css.rel='stylesheet';css.href='assets/tasks.css';document.head.append(css);}
  const script=el('script');script.src='assets/tasks.js';
  script.onload=()=>{tasksReady=true;tasksLoading=false;if(state.authenticated)renderMessages();};
  script.onerror=()=>{script.remove();tasksLoading=false;tasksFailed=true;if(state.authenticated)renderMessages();};
  document.head.append(script);
}
const labels = {legacy:'历史消息 · 当时的读取状态未记录',pending:'已提交 · 等待 AI 读取',client_read:'客户端已读取',attempting:'已保存 · 微信发送结果待确认',api_accepted:'已发送至微信接口',no_error_reported:'微信接口未报错',phone_confirmed:'微信已确认收到',api_rejected:'正文已保存 · 微信提醒发送失败',unconfirmed_do_not_retry:'正文已保存 · 微信提醒结果未确认'};
const errors = {image_too_large:'图片过大，请选择较小的图片。',invalid_image:'无法读取图片，请选择 JPG、PNG 或 WebP。',image_storage_full:'图片空间已满，请清理不需要的对话。',too_many_pending_images:'待发送图片较多，请稍后再试。',image_not_found:'图片不存在或已清理。',image_already_sent:'图片已经发送，请重新选择。',image_dimensions_unsupported:'图片尺寸或格式不支持，请尝试截图后发送。',conversation_name_conflict:'已有同名有效对话。请先归档同名对话，再恢复这一条。',login_required:'请重新登录。',invalid_login_code:'登录码不正确，请检查微信中的 8 位数字。',login_code_expired:'登录码已过期或尝试次数过多，请在微信重新发送 /web。',conversation_closed:'这个对话已结束或客户端已停用，暂时无法回复。',conversation_not_found:'对话不存在，请从列表重新选择。',message_not_found:'未找到链接指向的消息，请从对话列表进入。',request_id_content_conflict:'本次重试内容不一致，请保留原内容重试。'};
function error(text=''){ $('error').textContent=text; $('error').hidden=!text; }
Object.assign(errors,{task_not_found:'这张任务卡片不存在或已清理。',invalid_task_choice:'选项已失效，请重新打开卡片。',task_answer_required:'请选择一个方案，或写下你的安排。',task_already_answered:'这张卡片已经答复，不能重复更改决定。',task_not_pending:'这张卡片已经取消或结束。',task_expired:'这张卡片已过期，请在对话中请 AI 重新发起。',task_state_conflict:'任务状态已变化，请刷新查看。'});
errors.task_choice_limit='选择数量不符合这张卡片的要求，请调整后提交。';
Object.assign(errors,{invalid_conversation_name:'名称格式不正确，请使用 1–20 位中英文、数字、下划线或短横线。',conversation_name_conflict:'已有同名有效对话，请使用另一个名称。',invalid_task_fields:'表单内容格式不正确，请检查选项、数字或日期。',task_field_required:'请填写所有必填项。'});
function loginView(){state.authenticated=false;state.generation++;$('workspace').hidden=true;$('login').hidden=false;}
async function api(path,body){
  const response=await fetch('api/'+path,{method:body===undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',headers:body===undefined?{}:{'Content-Type':'application/json','X-Chat-Request':'1'},body:body===undefined?undefined:JSON.stringify(body)});
  const data=await response.json().catch(()=>({}));
  if(!response.ok){if(response.status===401&&path!=='login')loginView();const failure=new Error(errors[data.detail]||'暂时无法连接，请稍后重试。');failure.status=response.status;failure.code=data.detail;throw failure;}return data;
}
function date(value){if(!value)return '';const p=Object.fromEntries(new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(value*1000)).map(p=>[p.type,p.value]));return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}`;}
function el(tag,className,text){const n=document.createElement(tag);if(className)n.className=className;if(text!==undefined)n.textContent=text;return n;}
function markdown(target,text){
  // Messages are untrusted. Only formatting tags survive; no raw forms, media or scripts.
  target.innerHTML=DOMPurify.sanitize(marked.parse(text,{breaks:true,gfm:true}),{ALLOWED_TAGS:['p','br','strong','em','del','h1','h2','h3','h4','h5','h6','ul','ol','li','blockquote','pre','code','hr','table','thead','tbody','tr','th','td','a'],ALLOWED_ATTR:['href','title','start']});
  for(const a of target.querySelectorAll('a')){try{const href=a.getAttribute('href');if(!href)throw new Error();const u=new URL(href,location.href);if(!['http:','https:'].includes(u.protocol))throw new Error();a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';}catch{a.removeAttribute('href');}}
  for(const table of target.querySelectorAll('table')){const wrap=el('div','table-scroll');table.replaceWith(wrap);wrap.append(table);}
}
function renderChats(){
  $('pending-count').textContent=state.chats.reduce((n,c)=>n+c.pending_tasks,0);
  if(state.taskTab){renderTaskList();return;}
  const query=$('chat-search').value.trim().toLocaleLowerCase();
  const chats=state.chats.filter(c=>!!c.archived===!!state.archived&&(!query||(c.caller+' '+c.name).toLocaleLowerCase().includes(query)));
  $('more-tasks').hidden=true;
  $('chats').replaceChildren();$('empty-chats').hidden=!!chats.length;
  $('empty-chats').textContent=query?'没有匹配的对话。':state.archived?'还没有归档对话。归档后保留记录，随时可以查看。':'还没有对话。使用微信插件登记聊天名称即可开始。';
  for(const chat of chats){
    const b=el('button','chat-item'+(chat.id===state.cid?' selected':''));b.type='button';b.setAttribute('aria-label',chat.caller+' · '+chat.name);
    b.append(el('span','chat-name',`${chat.caller} · ${chat.name}${chat.archived?' · 已归档':chat.active?'':' · 已停用'}`),el('span','chat-preview',chat.preview),el('time','',date(chat.last_at)));
    if(chat.pinned)b.classList.add('pinned');
    if(chat.pinned||chat.pending_tasks||state.drafts.get(chat.id)){const badges=el('span','chat-hints');if(chat.pinned)badges.append(el('span','','置顶'));if(chat.pending_tasks)badges.append(el('span','task-hint',chat.pending_tasks+' 项待办'));if(state.drafts.get(chat.id))badges.append(el('span','draft-hint','草稿'));b.append(badges);}
    if(chat.unread)b.append(el('span','unread',chat.unread>99?'99+':String(chat.unread)));
    const row=el('div','chat-row');
    const del=el('button','swipe-delete','删除');del.type='button';del.setAttribute('aria-label','删除 '+chat.name);del.onclick=()=>confirmDelete(chat);
    const menu=el('button','row-menu','···');menu.type='button';menu.setAttribute('aria-label',chat.name+' 的操作');menu.onclick=()=>openActions(chat);
    b.onclick=()=>{if(row.classList.contains('swiped'))row.classList.remove('swiped');else selectChat(chat.id);};
    row.append(del,b,menu);bindLongPress(b,()=>openActions(chat));bindSwipe(row,()=>{document.querySelectorAll('.chat-row.swiped').forEach(n=>n.classList.remove('swiped'));row.classList.add('swiped');},()=>row.classList.remove('swiped'));
    $('chats').append(row);
  }
}
function renderTaskList(){
  $('chats').replaceChildren();$('empty-chats').hidden=!!taskList.length;$('empty-chats').textContent='没有待你答复的任务。已答复、过期或归档的卡片不会出现在这里。';
  for(const {task,conversation,message_id} of taskList){const b=el('button','pending-item');b.type='button';b.append(el('span','pending-source',conversation.caller+' · '+conversation.name),el('strong','',task.title),el('span','pending-expiry','有效期至 '+date(task.expires_at)),el('span','pending-action','查看并答复 →'));b.onclick=()=>selectChat(conversation.id,message_id);$('chats').append(b);}
  $('more-tasks').hidden=!taskCursor;
}
async function refreshTaskList(append=false){
  const generation=++taskListGeneration;const query=$('chat-search').value.trim();$('more-tasks').disabled=true;
  try{const data=await api('tasks?limit=30'+(append&&taskCursor?'&before='+taskCursor:'')+'&q='+encodeURIComponent(query));if(generation!==taskListGeneration||!state.taskTab)return;taskList=append?[...taskList,...data.tasks]:data.tasks;taskCursor=data.next_before;renderTaskList();}finally{$('more-tasks').disabled=false;}
}
function renderMessages(){
  const focused=document.activeElement?.closest('.task-card')?document.activeElement:null;
  const focus=focused?{id:focused.id,start:focused.selectionStart,end:focused.selectionEnd}:null;
  const fragment=document.createDocumentFragment();
  for(const m of [...state.messages.values()].sort((a,b)=>a.id-b.id)){
    const n=el('article','message '+m.direction+(m.id===state.anchor?' focused':''));n.id='message-'+m.id;
    const meta=el('div','message-meta');meta.append(el('span','',m.direction==='user'?(m.source==='web'?'你 · 网页':'你 · 微信'):$('chat-title').textContent),el('time','',date(m.created_at)));
    const bubble=el('div',m.task?'bubble':'bubble markdown');if(m.task){
      n.classList.add('task-message');
      if(tasksReady)bubble.append(renderTaskCard(m.task));
      else{loadTaskAssets();markdown(bubble,m.text);const retry=el('button','',tasksFailed?'重新加载卡片':'正在载入卡片…');retry.type='button';retry.disabled=!tasksFailed;retry.onclick=()=>{tasksFailed=false;loadTaskAssets();renderMessages();};bubble.append(retry);}
    }else markdown(bubble,m.text);
    for(const attachment of m.attachments||[]){const button=el('button','message-image');button.type='button';const img=el('img');img.src=`api/conversations/${m.conversation_id}/images/${attachment.id}`;img.alt='图片附件，点击放大';img.loading='lazy';button.append(img);button.onclick=()=>{$('full-image').src=img.src;$('image-viewer').showModal();};bubble.append(button);}
    const status=el('div','message-state'+(['api_rejected','unconfirmed_do_not_retry'].includes(m.status)?' failed':''),labels[m.status]||'已保存');n.append(meta,bubble,status);fragment.append(n);
  }
  $('messages').replaceChildren(fragment);$('empty-messages').hidden=!!state.messages.size;
  if(focus){const target=document.getElementById(focus.id);if(target&&!target.disabled){target.focus({preventScroll:true});if(typeof target.setSelectionRange==='function'&&focus.start!==null)target.setSelectionRange(focus.start,focus.end);}}
}
function merge(messages){let changed=false;for(const m of messages){const old=state.messages.get(m.id);if(!old||old.text!==m.text||old.status!==m.status||JSON.stringify(old.task)!==JSON.stringify(m.task)){state.messages.set(m.id,m);changed=true;}}if(changed)renderMessages();$('empty-messages').hidden=!!state.messages.size;}
function ids(){const a=[...state.messages.keys()];return {min:a.length?Math.min(...a):0,max:a.length?Math.max(...a):0};}
async function read(){if(document.hidden||!state.cid||!state.messages.size)return;await api(`conversations/${state.cid}/read`,{message_id:ids().max});}
async function refreshChats(){const data=await api('conversations');if(browserDrafts.open(data.draft_scope)){state.drafts.clear();state.pending.clear();for(const chat of data.conversations){const d=browserDrafts.get('reply:'+chat.id);if(d&&typeof d.text==='string'&&d.text.length<=20000){state.drafts.set(chat.id,d.text);if(d.pending&&typeof d.pending.request_id==='string')state.pending.set(chat.id,d.pending);}}}const changed=JSON.stringify(state.chats)!==JSON.stringify(data.conversations);state.chats=data.conversations;if((changed||!state.authenticated)&&!state.pressing&&!document.querySelector('.chat-row.swiped'))renderChats();}
function resizeReply(){$('reply').style.height='auto';$('reply').style.height=Math.min(144,$('reply').scrollHeight)+'px';}
function persistReply(cid){const text=state.drafts.get(cid)||'',pending=state.pending.get(cid);browserDrafts.set('reply:'+cid,text||pending?{text,pending}:null);}
function draftSave(){if(state.cid&&state.loadedCid===state.cid){state.drafts.set(state.cid,$('reply').value);persistReply(state.cid);}resizeReply();if(browserDrafts.failed)$('compose-note').textContent='浏览器存储不可用，草稿暂未保存；离开前请复制。';}
function composeState(active=true){
  const p=state.pending.get(state.cid);$('reply').readOnly=!!p;$('send').textContent=p?'重试':'发送';$('cancel-pending').hidden=!p;
  $('send').disabled=state.busy||!active;$('reply').disabled=!active;
  for(const id of ['pick-image','take-photo','attach-toggle'])$(id).disabled=state.busy||!!p||!active;renderImageDrafts();
  $('compose-note').textContent=!active?'只读对话，历史记录仍可查看。':p?'提交结果未确认，重试会复用同一条消息，不会重复入箱。':'回复发送到当前对话；已启用唤醒时自动通知 AI。';
}
async function selectChat(cid,anchor=0,push=true){
  draftSave();setAttachments(false);const generation=++state.generation;state.cid=cid;state.anchor=anchor;state.messages.clear();error();
  const url=new URL(location.href);url.searchParams.set('c',cid);if(anchor)url.searchParams.set('m',anchor);else url.searchParams.delete('m');if(push)history.pushState({wechatChat:true},'',url);else history.replaceState(history.state,'',url);
  $('workspace').classList.add('has-chat');$('welcome').hidden=true;$('scroll').hidden=false;$('composer').hidden=false;
  $('chat-title').textContent='正在载入对话…';$('reply').value=state.drafts.get(cid)||'';$('reply').disabled=true;$('send').disabled=true;$('messages').replaceChildren();renderChats();
  try{
    const data=await api(`conversations/${cid}/messages${anchor?'?around='+anchor:''}`);if(generation!==state.generation)return;
    const chat=data.conversation;$('chat-title').textContent=chat.caller+' · '+chat.name;$('chat-subtitle').textContent=chat.archived?'已归档 · 仅查看历史记录':'每条回复都会送到这个对话';$('reply-label').textContent='回复 '+chat.caller+' · '+chat.name;
    $('chat-menu').hidden=false;
    $('chat-badge').hidden=false;$('chat-badge').textContent=chat.archived?'已归档':chat.active?'对话中':'已停用';state.active=chat.active;
    state.loadedCid=cid;merge(data.messages);$('older').hidden=!data.has_older;state.hasNewer=data.has_newer;$('newer').hidden=!data.has_newer;composeState(chat.active);resizeReply();
    if(anchor)document.getElementById('message-'+anchor)?.scrollIntoView({block:'center'});else $('scroll').scrollTop=$('scroll').scrollHeight;
    await read();await refreshChats();
  }catch(e){if(generation===state.generation)error(e.message);}
}
async function loadPage(older){
  const cid=state.cid,generation=state.generation,scroll=$('scroll'),height=scroll.scrollHeight,top=scroll.scrollTop;
  const data=await api(`conversations/${cid}/messages?${older?'before='+ids().min:'after='+ids().max}`);if(generation!==state.generation)return;
  merge(data.messages);if(older){$('older').hidden=!data.has_older;scroll.scrollTop=top+scroll.scrollHeight-height;}else{state.hasNewer=data.has_newer;$('newer').hidden=!data.has_newer;await read();}
}
async function poll(){
  if(!state.authenticated||document.hidden||state.polling||state.busy||state.pressing||$('chat-actions').open||$('delete-confirm').open||$('rename-dialog').open||document.querySelector('dialog.field-sheet[open],.chat-row.swiped'))return;state.polling=true;
  try{
    await refreshChats();if(state.taskTab&&!$('workspace').classList.contains('has-chat')&&taskList.length<=30&&$('chats').scrollTop<80)await refreshTaskList();if(!state.cid)return;
    const generation=state.generation,cid=state.cid,scroll=$('scroll'),top=scroll.scrollTop,nearBottom=scroll.scrollHeight-scroll.clientHeight-top<100;
    if(tasksReady)await refreshTaskCards(cid,generation);if(generation!==state.generation||state.hasNewer)return;
    const max=ids().max;const data=await api(`conversations/${cid}/messages?after=${max}`);if(generation!==state.generation)return;
    const recent=max?await api(`conversations/${cid}/messages?before=${max+1}`):{messages:[]};if(generation!==state.generation)return;
    merge([...recent.messages,...data.messages]);state.hasNewer=data.has_newer;$('newer').hidden=!data.has_newer;state.active=data.conversation.active;composeState(state.active);
    scroll.scrollTop=nearBottom?scroll.scrollHeight:top;if(nearBottom)await read();error();
  }catch(e){if(state.authenticated)error(e.message);}finally{state.polling=false;}
}
$('login-form').onsubmit=async event=>{event.preventDefault();const b=event.currentTarget.querySelector('button');b.disabled=true;$('login-error').textContent='';try{await api('login',{code:$('login-code').value});$('login-code').value='';await start();}catch(e){$('login-error').textContent=e.message;}finally{b.disabled=false;}};
$('logout').onclick=async()=>{try{await api('logout',{});browserDrafts.clear();state.drafts.clear();state.pending.clear();if(tasksReady)clearTaskDrafts();for(const cid of imageDrafts.keys())clearImages(cid);state.messages.clear();$('messages').replaceChildren();$('reply').value='';loginView();}catch(e){error(e.message);}};
function showList(){draftSave();state.generation++;state.cid=null;state.messages.clear();$('messages').replaceChildren();$('workspace').classList.remove('has-chat');$('scroll').hidden=true;$('composer').hidden=true;$('welcome').hidden=false;$('chat-menu').hidden=true;$('chat-badge').hidden=true;$('chat-title').textContent='选择一个对话';error();renderChats();}
function goBack(){if(history.state?.wechatChat)history.back();else{const url=new URL(location.href);url.search='';history.replaceState(null,'',url);showList();}}
$('back').onclick=goBack;
window.addEventListener('popstate',()=>{const url=new URL(location.href),cid=url.searchParams.get('c');if(cid)selectChat(cid,Number(url.searchParams.get('m'))||0,false);else showList();});
function bindLongPress(node,action){
  let timer=null,start=null,suppressUntil=0;
  function cancel(){if(timer!==null)clearTimeout(timer);timer=null;start=null;state.pressing=false;}
  function open(){cancel();if(!node.isConnected)return;suppressUntil=Date.now()+900;action();}
  node.addEventListener('pointerdown',e=>{
    if(e.button!==0||!e.isPrimary||e.target.closest('button.swipe-delete'))return;
    cancel();start={x:e.clientX,y:e.clientY};state.pressing=true;
    timer=setTimeout(open,500);
  });
  node.addEventListener('pointermove',e=>{if(start&&Math.hypot(e.clientX-start.x,e.clientY-start.y)>10)cancel();});
  for(const event of ['pointerup','pointercancel','pointerleave','lostpointercapture'])node.addEventListener(event,cancel);
  node.addEventListener('click',e=>{if(Date.now()<suppressUntil){e.preventDefault();e.stopImmediatePropagation();}},true);
  node.addEventListener('contextmenu',e=>{e.preventDefault();if(Date.now()>=suppressUntil)open();});
  node.addEventListener('keydown',e=>{if(e.key==='ContextMenu'||(e.shiftKey&&e.key==='F10')){e.preventDefault();open();}});
}
function bindSwipe(node,left,right,edge=false){
  let start=null;
  node.addEventListener('touchstart',e=>{const t=e.touches[0];start=e.touches.length===1&&!e.target.closest('textarea,input,pre,.table-scroll')&&(!edge||t.clientX<32)?{x:t.clientX,y:t.clientY}:null;},{passive:true});
  node.addEventListener('touchmove',e=>{if(start){const t=e.touches[0];if(Math.abs(t.clientY-start.y)>25)start=null;}},{passive:true});
  node.addEventListener('touchend',e=>{if(!start||$('chat-actions').open||$('delete-confirm').open)return;const t=e.changedTouches[0],dx=t.clientX-start.x,dy=t.clientY-start.y;start=null;if(Math.abs(dx)>75&&Math.abs(dy)<25){if(dx<0)left?.();else right?.();}},{passive:true});
  node.addEventListener('touchcancel',()=>{start=null;},{passive:true});
}
bindSwipe($('scroll'),null,goBack,true);
bindLongPress($('chat-title'),()=>{const chat=state.chats.find(c=>c.id===state.cid);if(chat)openActions(chat);});
let actionChat=null;
function openActions(chat){actionChat=chat;$('actions-title').textContent=chat.caller+' · '+chat.name;$('archive-chat').textContent=chat.archived?'恢复对话':'归档对话';$('pin-chat').textContent=chat.pinned?'取消置顶':'置顶对话';$('chat-actions').showModal();}
function confirmDelete(chat){actionChat=chat;if($('chat-actions').open)$('chat-actions').close();$('delete-title').textContent='删除“'+chat.name+'”？';$('delete-confirm').showModal();}
$('chat-menu').onclick=()=>{const chat=state.chats.find(c=>c.id===state.cid);if(chat)openActions(chat);};
$('delete-chat').onclick=()=>confirmDelete(actionChat);
function setTab(archived,taskTab=false){state.archived=archived;state.taskTab=taskTab;taskListGeneration++;$('active-tab').setAttribute('aria-pressed',String(!archived&&!taskTab));$('archive-tab').setAttribute('aria-pressed',String(archived));$('pending-tab').setAttribute('aria-pressed',String(taskTab));renderChats();if(taskTab)refreshTaskList().catch(e=>error(e.message));}
$('active-tab').onclick=()=>setTab(false);$('archive-tab').onclick=()=>setTab(true);
$('pending-tab').onclick=()=>setTab(false,true);
$('chat-search').oninput=()=>{renderChats();clearTimeout(searchTimer);if(state.taskTab){taskListGeneration++;searchTimer=setTimeout(()=>refreshTaskList().catch(e=>error(e.message)),200);}};
$('more-tasks').onclick=()=>refreshTaskList(true).catch(e=>error(e.message));
$('pin-chat').onclick=async()=>{if(state.busy||!actionChat)return;state.busy=true;try{await api(`conversations/${actionChat.id}/pin`,{pinned:!actionChat.pinned});$('chat-actions').close();await refreshChats();}catch(e){error(e.message);}finally{state.busy=false;}};
$('rename-chat').onclick=()=>{$('chat-actions').close();$('rename-input').value=actionChat.name;$('rename-error').textContent='';$('rename-dialog').showModal();$('rename-input').focus();};
$('cancel-rename').onclick=()=>$('rename-dialog').close();
$('rename-form').onsubmit=async event=>{event.preventDefault();if(state.busy||!actionChat)return;const cid=actionChat.id;state.busy=true;$('save-name').disabled=true;try{await api(`conversations/${cid}/rename`,{name:$('rename-input').value.trim()});$('rename-dialog').close();await refreshChats();if(state.cid===cid)await selectChat(cid,0,false);}catch(e){$('rename-error').textContent=e.message;}finally{state.busy=false;$('save-name').disabled=false;if(state.authenticated)renderMessages();composeState(state.active);}};
$('archive-chat').onclick=async()=>{
  if(state.busy||!actionChat)return;const chat=actionChat;state.busy=true;$('archive-chat').disabled=true;
  try{await api(`conversations/${chat.id}/archive`,{archived:!chat.archived});$('chat-actions').close();await refreshChats();if(state.cid===chat.id)await selectChat(chat.id,0,false);setTab(!chat.archived);$('toast').textContent=chat.archived?'对话已恢复；如需自动唤醒，请在 AI 端重新启用。':'已归档，记录保留，手机端不能继续回复';$('toast').hidden=false;setTimeout(()=>$('toast').hidden=true,3500);}
  catch(e){$('chat-actions').close();$('toast').textContent=e.message;$('toast').hidden=false;setTimeout(()=>$('toast').hidden=true,5000);}finally{state.busy=false;$('archive-chat').disabled=false;if(state.authenticated)renderMessages();composeState(state.active);}
};
for(const id of ['chat-actions','delete-confirm','rename-dialog'])$(id).addEventListener('click',e=>{if(e.target===$(id))$(id).close();});
$('confirm-delete').onclick=async()=>{
  if(state.busy||!actionChat)return;const cid=actionChat.id;state.busy=true;$('confirm-delete').disabled=true;error();
  try{await api(`conversations/${cid}/delete`,{});document.querySelectorAll('.chat-row.swiped').forEach(n=>n.classList.remove('swiped'));state.drafts.delete(cid);state.pending.delete(cid);persistReply(cid);if(tasksReady)clearConversationTaskDrafts(cid);clearImages(cid);if(state.cid===cid){$('reply').value='';const url=new URL(location.href);url.search='';history.replaceState(null,'',url);showList();}await refreshChats();if(state.taskTab)await refreshTaskList();$('delete-confirm').close();$('toast').textContent='对话已删除';$('toast').hidden=false;setTimeout(()=>$('toast').hidden=true,2500);}
  catch(e){$('delete-confirm').close();error(e.message);$('toast').textContent=e.message;$('toast').hidden=false;setTimeout(()=>$('toast').hidden=true,5000);}finally{state.busy=false;$('confirm-delete').disabled=false;}
};
$('refresh').onclick=async()=>{try{await refreshChats();if(state.taskTab)await refreshTaskList();}catch(e){error(e.message);}};
$('older').onclick=()=>loadPage(true).catch(e=>error(e.message));$('newer').onclick=()=>loadPage(false).catch(e=>error(e.message));
$('cancel-pending').onclick=()=>{state.pending.delete(state.cid);persistReply(state.cid);composeState(state.active);error('已取消重试。如果之前的提交已到达服务器，消息仍会保留在记录中。');};
function clearImages(cid){for(const item of imageDrafts.get(cid)||[])URL.revokeObjectURL(item.url);imageDrafts.delete(cid);}
function renderImageDrafts(){
  $('image-drafts').replaceChildren();const count=(imageDrafts.get(state.cid)||[]).length;$('image-count').textContent=count?`${count} / 3 张图片`:'最多 3 张图片';
  for(const item of imageDrafts.get(state.cid)||[]){const wrap=el('div','image-draft'),img=el('img'),remove=el('button','','×');img.src=item.url;img.alt='待发送图片';remove.type='button';remove.setAttribute('aria-label','移除图片');remove.disabled=state.busy||state.pending.has(state.cid)||!state.active;remove.onclick=()=>{const items=imageDrafts.get(state.cid);items.splice(items.indexOf(item),1);URL.revokeObjectURL(item.url);if(!items.length)imageDrafts.delete(state.cid);renderImageDrafts();};wrap.append(img,remove);$('image-drafts').append(wrap);}
}
async function preparePhoto(file){
  if(file.size>20*1024*1024)throw new Error('请选择小于 20 MB 的图片。');
  const url=URL.createObjectURL(file),img=new Image();
  try{img.src=url;await img.decode();const scale=Math.min(1,2048/Math.max(img.naturalWidth,img.naturalHeight)),canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.round(img.naturalWidth*scale));canvas.height=Math.max(1,Math.round(img.naturalHeight*scale));canvas.getContext('2d').drawImage(img,0,0,canvas.width,canvas.height);const blob=await new Promise(resolve=>canvas.toBlob(resolve,file.type==='image/png'?'image/png':'image/jpeg',0.9));if(!blob||blob.size>5*1024*1024)throw new Error('图片过大，请尝试截图后发送。');return {blob,url:URL.createObjectURL(blob)};}
  finally{URL.revokeObjectURL(url);}
}
async function chooseImages(input){
  const cid=state.cid,files=[...input.files];input.value='';if(!cid||state.busy||state.pending.has(cid)||!state.active)return;
  if((imageDrafts.get(cid)||[]).length+files.length>3){error('每条消息最多发送 3 张图片。');return;}
  state.busy=true;composeState(state.active);error();
  try{for(const file of files){const item=await preparePhoto(file);const items=imageDrafts.get(cid)||[];items.push(item);imageDrafts.set(cid,items);}}
  catch(e){error(e.message||'无法读取这张图片，请尝试截图。');}finally{state.busy=false;setAttachments(false);composeState(state.active);}
}
function setAttachments(open){$('attachment-panel').hidden=!open;$('attach-toggle').setAttribute('aria-expanded',String(open));$('attach-toggle').setAttribute('aria-label',open?'收起附件':'添加图片');}
$('attach-toggle').onclick=()=>setAttachments($('attachment-panel').hidden);
$('reply').addEventListener('focus',()=>setAttachments(false));
$('composer').addEventListener('keydown',e=>{if(e.key==='Escape'){setAttachments(false);$('attach-toggle').focus();}});
$('pick-image').onclick=()=>$('image-files').click();$('take-photo').onclick=()=>$('camera-file').click();
for(const id of ['image-files','camera-file'])$(id).onchange=()=>chooseImages($(id));
$('close-image').onclick=()=>$('image-viewer').close();$('image-viewer').addEventListener('click',e=>{if(e.target===$('image-viewer'))$('image-viewer').close();});$('image-viewer').addEventListener('close',()=>$('full-image').removeAttribute('src'));
$('reply').oninput=draftSave;
$('composer').onsubmit=async event=>{
  event.preventDefault();if(state.busy||!state.cid||!state.active||(!$('reply').value.trim()&&!(imageDrafts.get(state.cid)||[]).length))return;
  const cid=state.cid,generation=state.generation;const pending=state.pending.get(cid)||{text:$('reply').value,request_id:crypto.randomUUID(),attachment_ids:[]};state.pending.set(cid,pending);state.busy=true;composeState(state.active);error();
  try{for(const item of imageDrafts.get(cid)||[]){if(!item.id){const response=await fetch(`api/conversations/${cid}/images`,{method:'POST',credentials:'same-origin',headers:{'Content-Type':item.blob.type,'X-Chat-Request':'1'},body:item.blob});const uploaded=await response.json().catch(()=>({}));if(!response.ok){if(response.status===401)loginView();throw new Error(errors[uploaded.detail]||'图片上传失败，请重试。');}item.id=uploaded.id;}}if(imageDrafts.has(cid))pending.attachment_ids=imageDrafts.get(cid).map(x=>x.id);persistReply(cid);const data=await api(`conversations/${cid}/messages`,pending);clearImages(cid);state.pending.delete(cid);state.drafts.delete(cid);persistReply(cid);if(generation===state.generation){$('reply').value='';resizeReply();setAttachments(false);merge([data.message]);$('scroll').scrollTop=$('scroll').scrollHeight;}$('compose-note').textContent='已提交，等待 AI 读取。';await refreshChats();}
  catch(e){if(generation===state.generation)error(e.message);}finally{state.busy=false;composeState(state.active);}
};
$('reply').onkeydown=event=>{if(event.key==='Enter'&&(event.ctrlKey||event.metaKey)){event.preventDefault();$('composer').requestSubmit();}};
window.addEventListener('beforeunload',event=>{draftSave();if(browserDrafts.failed||imageDrafts.size){event.preventDefault();event.returnValue='';}});
async function start(){try{await refreshChats();state.authenticated=true;$('login').hidden=true;$('workspace').hidden=false;if(state.cid)await selectChat(state.cid,state.anchor,false);}catch(e){loginView();if(e.message!=='请重新登录。')$('login-error').textContent=e.message;}}
start();setInterval(poll,5000);
