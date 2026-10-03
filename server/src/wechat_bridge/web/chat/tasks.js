'use strict';
const taskDrafts = new Map(), taskPending = new Map(), taskErrors = new Map();
const taskLabels = {pending:'待你决定',answered:'已答复',processing:'处理中',completed:'已完成',cancelled:'已取消',expired:'已过期'};

function taskDirty(){return [...taskDrafts.values()].some(d=>d.choice_id!==undefined||d.choice_ids.length||d.text.trim())||taskPending.size>0;}
function clearTaskDrafts(){taskDrafts.clear();taskPending.clear();taskErrors.clear();}
function persistTask(id,draft){browserDrafts.set('task:'+id,draft?{draft,pending:taskPending.get(id)}:null);}
function clearConversationTaskDrafts(cid){for(const [id,draft] of taskDrafts)if(draft.cid===cid){persistTask(id,null);taskDrafts.delete(id);taskPending.delete(id);taskErrors.delete(id);}}
function taskCanSubmit(task,draft){
  const mode=task.mode||'single';
  if(mode==='form')return task.fields.every(f=>!f.required||!!(draft.field_values[f.id]||'').trim());
  if(mode==='input')return !!draft.text.trim();
  if(mode==='multiple'){const n=draft.choice_ids.length;return n? n>=task.min_choices&&n<=task.max_choices :task.allow_custom&&!!draft.text.trim();}
  return draft.choice_id!==undefined&&(draft.choice_id!==null||(task.allow_custom&&!!draft.text.trim()));
}
function taskAnswerPayload(task,draft){
  if(task.mode==='form')return {field_values:{...draft.field_values}};
  if(task.mode==='multiple')return {choice_ids:[...draft.choice_ids],text:task.allow_custom?draft.text:''};
  if(task.mode==='input')return {choice_id:null,text:draft.text};
  return {choice_id:draft.choice_id,text:draft.choice_id===null?draft.text:''};
}
function renderTaskCard(task){
  const mode=task.mode||'single',card=el('section','task-card');card.dataset.taskId=task.id;card.setAttribute('aria-label','任务卡片：'+task.title);
  const head=el('div','task-card-head');head.append(el('span','task-kind',['input','form'].includes(mode)?'需要你补充':'需要你的决定'),el('span','task-status '+task.status,['input','form'].includes(mode)&&task.status==='pending'?'待你填写':taskLabels[task.status]||task.status));
  const prompt=el('div','task-prompt markdown');markdown(prompt,task.prompt);card.append(head,el('h2','task-title',task.title),prompt);
  if(task.status!=='pending'){
    taskDrafts.delete(task.id);taskPending.delete(task.id);taskErrors.delete(task.id);persistTask(task.id,null);
    if(task.answer){const answer=el('div','task-answer'),selected=task.answer.choice_labels?.join('、')||task.answer.choice_label;
      answer.append(el('span','task-answer-label',['input','form'].includes(mode)?'你的回复':'你的决定'));
      if(selected)answer.append(el('strong','',selected));else if(!['input','form'].includes(mode))answer.append(el('strong','','自行回复'));
      for(const field of task.answer.fields||[])answer.append(el('p','',field.label+'：'+(field.value||'未填写')));
      if(task.answer.text)answer.append(el('p','',task.answer.text));card.append(answer);
    }
    if(task.result){const result=el('div','task-result markdown');markdown(result,task.result);card.append(result);}
    if(task.status==='answered')card.append(el('p','task-note','回复已提交，等待 AI 处理。'));
    if(task.status==='expired')card.append(el('p','task-note','这张卡片已过期，可以在对话中请 AI 重新发起。'));
    return card;
  }
  const saved=browserDrafts.get('task:'+task.id);
  if(!taskDrafts.has(task.id)&&saved?.draft?.cid===task.conversation_id&&typeof saved.draft.text==='string'&&Array.isArray(saved.draft.choice_ids)){taskDrafts.set(task.id,saved.draft);if(saved.pending)taskPending.set(task.id,saved.pending);}
  const draft=taskDrafts.get(task.id)||{choice_id:undefined,choice_ids:[],text:'',field_values:{},cid:task.conversation_id};draft.field_values=draft.field_values||{};
  if(mode==='form')return renderFormCard(task,card,draft);
  const pending=taskPending.get(task.id),readonly=!!pending||!task.can_answer;
  const form=el('form','task-form'),choices=el('fieldset','task-choices');choices.disabled=state.busy||readonly;
  choices.append(el('legend','sr-only',mode==='multiple'?'选择需要的项目':'选择一个方案'));
  const customWrap=el('div','task-custom'),customLabel=el('label','','你的安排'),custom=el('textarea');custom.id='task-'+task.id+'-custom';customLabel.htmlFor=custom.id;custom.rows=3;custom.maxLength=2000;
  custom.placeholder=mode==='input'?(task.input_hint||'填写你的回复…'):mode==='multiple'?'可补充说明，或只填写自己的安排':'写下你的安排…';custom.value=draft.text;custom.disabled=state.busy||readonly;
  if(mode==='multiple')customLabel.textContent='补充说明或自行回复';if(mode==='input')customLabel.textContent='你的回复';customWrap.append(customLabel,custom);
  const feedback=el('p','task-feedback');feedback.setAttribute('role','status');
  const count=el('p','task-selection-count');count.setAttribute('role','status');
  const submit=el('button','task-submit',pending?'重试提交':mode==='input'?'提交回复':'提交决定');submit.type='submit';
  const actionButtons=[],customToggle=el('button','task-custom-toggle','自行回复');customToggle.type='button';
  function save(){taskDrafts.set(task.id,draft);persistTask(task.id,draft);taskErrors.delete(task.id);refreshForm();}
  function optionBody(option){const body=el('span','task-option-body'),title=el('span','task-option-title',option.label);if(option.recommended)title.append(el('span','task-recommended','推荐'));body.append(title);if(option.description)body.append(el('span','task-option-description',option.description));return body;}
  function optionRow(option){
    const row=el('label','task-option'),input=el('input');input.type=mode==='multiple'?'checkbox':'radio';input.name='task-choice-'+task.id;input.id='task-'+task.id+'-choice-'+(option.id===null?'custom':'preset-'+option.id);
    input.checked=mode==='multiple'?draft.choice_ids.includes(option.id):draft.choice_id===option.id;
    input.onchange=()=>{if(mode==='multiple'){draft.choice_ids=input.checked?[...draft.choice_ids,option.id]:draft.choice_ids.filter(id=>id!==option.id);}else draft.choice_id=option.id;save();};row.append(input,optionBody(option));return row;
  }
  if(mode==='confirm'){
    const actions=el('div','task-actions');
    for(const option of task.options){const button=el('button','task-action');button.type='button';button.append(optionBody({...option,label:pending?.choice_id===option.id?'重试：'+option.label:option.label}));button.onclick=()=>{draft.choice_id=option.id;taskDrafts.set(task.id,draft);submitTaskCard(task,draft);};actionButtons.push([button,option.id]);actions.append(button);}
    form.append(actions);
    if(task.allow_custom){customToggle.onclick=()=>{draft.choice_id=null;save();custom.focus();};form.append(customToggle);}
  }else if(mode!=='input'){
    for(const option of task.options)choices.append(optionRow(option));
    if(mode==='single'&&task.allow_custom)choices.append(optionRow({id:null,label:'自行回复',description:'按你的想法安排'}));
    form.append(choices);if(mode==='multiple')form.append(count);
  }
  function refreshForm(){
    const writing=mode==='input'||(mode==='multiple'&&task.allow_custom)||draft.choice_id===null;
    customWrap.hidden=!writing;submit.hidden=mode==='confirm'&&draft.choice_id!==null;
    submit.disabled=state.busy||!task.can_answer||(!pending&&!taskCanSubmit(task,draft));
    customToggle.disabled=state.busy||readonly;
    for(const [button,id] of actionButtons)button.disabled=state.busy||!task.can_answer||!!pending&&pending.choice_id!==id;
    for(const row of choices.querySelectorAll('.task-option')){const input=row.querySelector('input');row.classList.toggle('chosen',input.checked);input.disabled=state.busy||readonly||mode==='multiple'&&!input.checked&&draft.choice_ids.length>=task.max_choices;}
    count.textContent=`已选 ${draft.choice_ids.length} 项 · 需选 ${task.min_choices}–${task.max_choices} 项`;
    feedback.textContent=taskErrors.get(task.id)||(browserDrafts.failed?'浏览器存储不可用，草稿暂未保存；离开前请复制。':'');feedback.hidden=!feedback.textContent;
  }
  custom.oninput=()=>{draft.text=custom.value;save();};
  if(!task.can_answer)card.append(el('p','task-note','对话已归档或停用，这张卡片暂时只读。'));
  form.append(customWrap,feedback,submit,el('p','task-deadline','有效期至 '+date(task.expires_at)));card.append(form);refreshForm();
  form.onsubmit=event=>{event.preventDefault();submitTaskCard(task,draft);};return card;
}

async function submitTaskCard(task,draft){
  if(state.busy||!task.can_answer||!taskCanSubmit(task,draft))return;
  const cid=task.conversation_id,generation=state.generation;
  const pending=taskPending.get(task.id)||{request_id:crypto.randomUUID(),...taskAnswerPayload(task,draft)};
  taskPending.set(task.id,pending);taskDrafts.set(task.id,draft);persistTask(task.id,draft);state.busy=true;taskErrors.delete(task.id);renderMessages();composeState(state.active);
  try{
    const data=await api(`conversations/${cid}/tasks/${task.id}/answer`,pending);
    taskPending.delete(task.id);taskDrafts.delete(task.id);taskErrors.delete(task.id);persistTask(task.id,null);
    if(generation===state.generation){applyTasks([data.task]);merge([data.message]);$('scroll').scrollTop=$('scroll').scrollHeight;}
    if(state.authenticated)await refreshChats();
  }catch(e){
    if(e.status>=400&&e.status<500)taskPending.delete(task.id);
    persistTask(task.id,draft);
    if(state.authenticated){taskErrors.set(task.id,e.message||'提交结果未确认，请重试。');if(generation===state.generation)await refreshTaskCards(cid,generation).catch(()=>{});}
  }finally{state.busy=false;if(state.authenticated)renderMessages();composeState(state.active);}
}

function renderFormCard(task,card,draft){
  if(!document.getElementById('form-style')){const css=el('link');css.id='form-style';css.rel='stylesheet';css.href='assets/forms.css';document.head.append(css);}
  const pending=taskPending.get(task.id),form=el('form','task-form'),fields=el('fieldset','task-fields');fields.disabled=state.busy||!!pending||!task.can_answer;
  const submit=el('button','task-submit',pending?'重试提交':'提交表单');submit.type='submit';
  const feedback=el('p','task-feedback');feedback.setAttribute('role','status');
  function refresh(){submit.disabled=state.busy||!task.can_answer||(!pending&&!taskCanSubmit(task,draft));feedback.textContent=taskErrors.get(task.id)||(browserDrafts.failed?'浏览器存储不可用，草稿暂未保存；离开前请复制。':'');feedback.hidden=!feedback.textContent;}
  for(const field of task.fields){const group=el('div','task-field'),id='task-'+task.id+'-field-'+field.id,label=el('label','',field.label);label.htmlFor=id;label.append(el('span','field-required',field.required?'必填':'选填'));
    const input=el(field.type==='select'?'select':'input');input.id=id;input.name=field.id;input.required=field.required;
    if(field.type==='select'){input.append(new Option('请选择…',''));for(const option of field.options)input.append(new Option(option.label,option.id));}
    else{input.type=field.type==='number'?'text':field.type;input.maxLength=1000;input.placeholder=field.placeholder;if(field.type==='number')input.inputMode='decimal';}
    input.value=draft.field_values[field.id]||'';input.oninput=()=>{draft.field_values[field.id]=input.value;taskDrafts.set(task.id,draft);persistTask(task.id,draft);refresh();};group.append(label,input);fields.append(group);
  }
  form.append(fields,feedback,submit,el('p','task-deadline','有效期至 '+date(task.expires_at)));form.onsubmit=event=>{event.preventDefault();submitTaskCard(task,draft);};card.append(form);if(!task.can_answer)card.append(el('p','task-note','对话已归档或停用，表单暂时只读。'));refresh();return card;
}

function applyTasks(tasks){
  const values=new Map(tasks.map(task=>[task.id,task]));let changed=false;
  for(const message of state.messages.values())if(message.task&&values.has(message.task.id)){const task=values.get(message.task.id);if(JSON.stringify(task)!==JSON.stringify(message.task)){message.task=task;changed=true;}}
  if(changed)renderMessages();
}
async function refreshTaskCards(cid,generation){
  const ids=[...new Set([...state.messages.values()].filter(m=>m.task&&['pending','answered','processing'].includes(m.task.status)).map(m=>m.task.id))];
  for(let start=0;start<ids.length;start+=100){const data=await api(`conversations/${cid}/tasks?ids=${ids.slice(start,start+100).join(',')}`);if(generation!==state.generation)return;applyTasks(data.tasks);}
}
