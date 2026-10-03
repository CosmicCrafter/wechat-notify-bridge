'use strict';
const taskDrafts = new Map(), taskPending = new Map(), taskErrors = new Map();
const taskLabels = {pending:'待你决定',answered:'已答复',processing:'处理中',completed:'已完成',cancelled:'已取消',expired:'已过期'};

function taskDirty(){return [...taskDrafts.values()].some(d=>d.choice_id!==undefined||d.text.trim())||taskPending.size>0;}
function clearTaskDrafts(){taskDrafts.clear();taskPending.clear();taskErrors.clear();}
function clearConversationTaskDrafts(cid){for(const [id,draft] of taskDrafts)if(draft.cid===cid){taskDrafts.delete(id);taskPending.delete(id);taskErrors.delete(id);}}
function renderTaskCard(task){
  const card=el('section','task-card');card.dataset.taskId=task.id;card.setAttribute('aria-label','任务卡片：'+task.title);
  const head=el('div','task-card-head');head.append(el('span','task-kind','需要你的决定'),el('span','task-status '+task.status,taskLabels[task.status]||task.status));
  const title=el('h2','task-title',task.title),prompt=el('div','task-prompt markdown');markdown(prompt,task.prompt);card.append(head,title,prompt);
  const draft=taskDrafts.get(task.id)||{choice_id:undefined,text:'',cid:task.conversation_id};
  const pending=taskPending.get(task.id),disabled=state.busy||!!pending||!task.can_answer;
  const form=el('form','task-form'),choices=el('fieldset','task-choices');choices.disabled=disabled;
  choices.append(el('legend','sr-only','选择一个方案'));
  const select=(id)=>{draft.choice_id=id;taskDrafts.set(task.id,draft);taskErrors.delete(task.id);refreshForm();};
  function optionRow(id,label,description,recommended){
    const row=el('label','task-option'),radio=el('input');radio.type='radio';radio.name='task-choice-'+task.id;radio.id='task-'+task.id+'-choice-'+(id===null?'custom':'preset-'+id);radio.checked=draft.choice_id===id;radio.onchange=()=>select(id);
    const body=el('span','task-option-body'),heading=el('span','task-option-title',label);if(recommended)heading.append(el('span','task-recommended','推荐'));
    body.append(heading);if(description)body.append(el('span','task-option-description',description));row.append(radio,body);return row;
  }
  for(const option of task.options)choices.append(optionRow(option.id,option.label,option.description,option.recommended));
  if(task.allow_custom)choices.append(optionRow(null,'自行回复','按你的想法安排',false));
  const customWrap=el('div','task-custom'),customLabel=el('label','','你的安排'),custom=el('textarea');custom.id='task-'+task.id+'-custom';customLabel.htmlFor=custom.id;custom.rows=3;custom.maxLength=2000;custom.placeholder='写下你的安排…';custom.value=draft.text;custom.disabled=disabled;
  custom.oninput=()=>{draft.text=custom.value;taskDrafts.set(task.id,draft);refreshForm();};customWrap.append(customLabel,custom);
  const feedback=el('p','task-feedback');feedback.setAttribute('role','status');
  const submit=el('button','task-submit',pending?'重试提交':'提交决定');submit.type='submit';
  function refreshForm(){
    customWrap.hidden=draft.choice_id!==null;submit.disabled=state.busy||!task.can_answer||(!pending&&(draft.choice_id===undefined||(draft.choice_id===null&&!draft.text.trim())));
    for(const label of choices.querySelectorAll('.task-option'))label.classList.toggle('chosen',label.querySelector('input').checked);
    feedback.textContent=taskErrors.get(task.id)||'';feedback.hidden=!feedback.textContent;
  }
  if(task.status==='pending'){
    if(!task.can_answer)card.append(el('p','task-note','对话已归档或停用，这张卡片暂时只读。'));
    form.append(choices,customWrap,feedback,submit,el('p','task-deadline','有效期至 '+date(task.expires_at)));card.append(form);refreshForm();
    form.onsubmit=event=>{event.preventDefault();submitTaskCard(task,draft);};
  }else{
    taskDrafts.delete(task.id);taskPending.delete(task.id);taskErrors.delete(task.id);
    if(task.answer){const answer=el('div','task-answer');answer.append(el('span','task-answer-label','你的决定'),el('strong','',task.answer.choice_label||'自行回复'));if(task.answer.text)answer.append(el('p','',task.answer.text));card.append(answer);}
    if(task.result){const result=el('div','task-result markdown');markdown(result,task.result);card.append(result);}
    if(task.status==='answered')card.append(el('p','task-note','决定已提交，等待 AI 处理。'));
    if(task.status==='expired')card.append(el('p','task-note','这张卡片已过期，可以在对话中请 AI 重新发起。'));
  }
  return card;
}

async function submitTaskCard(task,draft){
  if(state.busy||!task.can_answer||draft.choice_id===undefined)return;
  const cid=task.conversation_id,generation=state.generation;
  const pending=taskPending.get(task.id)||{request_id:crypto.randomUUID(),choice_id:draft.choice_id,text:draft.choice_id===null?draft.text:''};
  taskPending.set(task.id,pending);state.busy=true;taskErrors.delete(task.id);renderMessages();composeState(state.active);
  try{
    const data=await api(`conversations/${cid}/tasks/${task.id}/answer`,pending);
    taskPending.delete(task.id);taskDrafts.delete(task.id);taskErrors.delete(task.id);
    if(generation===state.generation){applyTasks([data.task]);merge([data.message]);$('scroll').scrollTop=$('scroll').scrollHeight;}
    await refreshChats();
  }catch(e){
    if(e.status>=400&&e.status<500)taskPending.delete(task.id);
    taskErrors.set(task.id,e.message||'提交结果未确认，请重试。');
    if(generation===state.generation)await refreshTaskCards(cid,generation).catch(()=>{});
  }finally{state.busy=false;if(state.authenticated)renderMessages();composeState(state.active);}
}

function applyTasks(tasks){
  const values=new Map(tasks.map(task=>[task.id,task]));let changed=false;
  for(const message of state.messages.values())if(message.task&&values.has(message.task.id)){const task=values.get(message.task.id);if(JSON.stringify(task)!==JSON.stringify(message.task)){message.task=task;changed=true;}}
  if(changed)renderMessages();
}
async function refreshTaskCards(cid,generation){
  const ids=[...new Set([...state.messages.values()].filter(m=>m.task).map(m=>m.task.id))];
  for(let start=0;start<ids.length;start+=100){const data=await api(`conversations/${cid}/tasks?ids=${ids.slice(start,start+100).join(',')}`);if(generation!==state.generation)return;applyTasks(data.tasks);}
}
