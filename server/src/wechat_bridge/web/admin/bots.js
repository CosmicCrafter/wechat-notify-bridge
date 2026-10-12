'use strict';
let botRecords=[], selectedBotId=null, grantClient=null, botPair=null, botQrUrl='', botQrVersion='';
let createScopeLoaded=false;
const botName=id=>botRecords.find(bot=>bot.id===id)?.name||id;
const botPlatform=value=>value==='wechat'?'微信':'飞书';
Object.assign(errors,{bot_name_conflict:'这个 Bot 名称已存在。',invalid_bot_name:'请输入 1–40 个字符的 Bot 名称。',
  invalid_bot_settings:'请检查 Bot 名称、应用 ID、本人 Open ID 和凭据字段是否完整且格式正确。',
  bot_binding_conflict:'这个机器人已经绑定到另一个 Bot，请使用不同的机器人。',invalid_bot_grants:'默认 Bot 必须属于允许调用的 Bot。',
  bot_disabled:'这个 Bot 已停用，请先启用。',bot_not_found:'Bot 已不存在，请刷新列表。'});

function dropBotQr(){
  if(botQrUrl)URL.revokeObjectURL(botQrUrl);
  botQrUrl='';botQrVersion='';$('bot-qr').removeAttribute('src');$('bot-qr').hidden=true;
}
function resetBots(){
  dropBotQr();botRecords=[];selectedBotId=null;grantClient=null;botPair=null;createScopeLoaded=false;
  $('bot-list').replaceChildren();$('bot-detail').hidden=true;$('key-bot-editor').hidden=true;
  $('new-bot-name').value='';$('bot-verify-code').value='';$('bot-rebind-confirm').hidden=true;
}
function drawGrants(container,selector,ids,defaultId){
  container.replaceChildren(...botRecords.map(bot=>{
    const label=document.createElement('label');label.className='bot-grant-option';
    const input=document.createElement('input');input.type='checkbox';input.value=bot.id;input.checked=ids.includes(bot.id);
    input.onchange=()=>drawDefaults(container,selector,selector.value);
    label.append(input,document.createTextNode(`${bot.name} · ${botPlatform(bot.platform)}${bot.enabled?'':' · 已停用'}`));return label;
  }));drawDefaults(container,selector,defaultId);
}
function drawDefaults(container,selector,current){
  const ids=[...container.querySelectorAll('input:checked')].map(input=>input.value);
  const empty=document.createElement('option');empty.value='';empty.textContent='不设默认（调用时指定 Bot）';
  selector.replaceChildren(empty,...ids.map(id=>{const option=document.createElement('option');option.value=id;option.textContent=botName(id);return option;}));
  selector.value=ids.includes(current)?current:'';
}
function createBotScope(){return {bot_ids:[...$('create-bot-grants').querySelectorAll('input:checked')].map(input=>input.value),default_bot_id:$('create-default-bot').value||null};}
async function loadBots(current=generation){
  const result=await api('bots');if(current!==generation||!key)return;
  const old=JSON.stringify(botRecords.map(bot=>[bot.id,bot.name,bot.enabled]));botRecords=result.bots;
  if(!createScopeLoaded||old!==JSON.stringify(botRecords.map(bot=>[bot.id,bot.name,bot.enabled]))){
    const scope=createScopeLoaded?createBotScope():{bot_ids:['default'],default_bot_id:'default'};
    drawGrants($('create-bot-grants'),$('create-default-bot'),scope.bot_ids,scope.default_bot_id);createScopeLoaded=true;
  }
  $('bot-list').replaceChildren(...botRecords.map(bot=>{
    const item=document.createElement('section');item.className='card bot-card';
    const heading=document.createElement('div');heading.className='card-heading';
    const name=document.createElement('h3');name.textContent=bot.name;
    const badge=document.createElement('span');badge.className='badge';badge.textContent=botPlatform(bot.platform)+(bot.enabled?' · 已启用':' · 已停用');heading.append(name,badge);
    const status=document.createElement('p');status.className='muted';status.textContent=bot.platform==='wechat'?(labels[bot.status.connection_status]?.[0]||'等待连接'):(bot.status.configured?'凭据已保存':'等待配置应用');
    const id=document.createElement('code');id.className='bot-id';id.textContent=`bot_id: ${bot.id}`;
    const actions=document.createElement('div');actions.className='actions';
    const edit=document.createElement('button');edit.type='button';edit.textContent='配置 Bot';edit.onclick=()=>openBot(bot.id);
    const toggle=document.createElement('button');toggle.type='button';toggle.className='secondary';toggle.textContent=bot.enabled?'停用':'启用';
    toggle.onclick=()=>act(async()=>{await api(`bots/${bot.id}`,{name:bot.name,enabled:!bot.enabled});await loadBots();});
    const rename=document.createElement('button');rename.type='button';rename.className='text-button';rename.textContent='改名';
    rename.onclick=()=>{selectedBotId=bot.id;$('bot-detail').hidden=false;$('bot-wechat').hidden=true;$('bot-detail-title').textContent=bot.name;$('rename-bot-name').value=bot.name;$('bot-detail').scrollIntoView({block:'nearest'});};
    actions.append(edit,toggle,rename);item.append(heading,status,id,actions);return item;
  }));
  if(selectedBotId&&location.hash==='#bots'&&botRecords.find(bot=>bot.id===selectedBotId)?.platform==='wechat')await refreshBotPair(current);
}
async function openBot(id){
  const bot=botRecords.find(bot=>bot.id===id);if(!bot)return;
  selectedBotId=id;dropBotQr();botPair=null;$('bot-verify-code').value='';$('bot-rebind-confirm').hidden=true;
  if(bot.platform==='feishu'){
    feishuLoaded=false;$('feishu-form').reset();location.hash='feishu';
    $('feishu-title').textContent=bot.name;try{await loadFeishu();}catch(error){showError(error.message);}return;
  }
  if(id==='default'){location.hash='overview';return;}
  location.hash='bots';$('bot-detail-title').textContent=bot.name;$('rename-bot-name').value=bot.name;
  $('bot-detail').hidden=false;$('bot-wechat').hidden=false;
  await refreshBotPair();$('bot-detail').scrollIntoView({block:'nearest'});
}
async function refreshBotPair(current=generation){
  const id=selectedBotId;if(!id)return;
  const result=await api(`bots/${id}/pairing`);if(current!==generation||!key||id!==selectedBotId)return;
  botPair=result.pairing;$('bot-pair-message').textContent=botPair.message;
  $('bot-wechat-status').textContent=labels[result.service.connection_status]?.[0]||'等待连接';
  $('bot-pair-start').disabled=botPair.active;$('bot-pair-start').textContent=result.service.bound?'重新绑定':'生成二维码';
  $('bot-pair-cancel').hidden=!botPair.active;$('bot-verify-form').hidden=botPair.phase!=='need_verifycode';
  const version=`${botPair.session_id}/${botPair.qr_version}`;
  if(!botPair.qr_available)dropBotQr();
  else if(version!==botQrVersion){
    const blob=await api(`bots/${id}/pairing/qr?session_id=${encodeURIComponent(botPair.session_id)}`,undefined,true);
    if(current!==generation||!key||id!==selectedBotId)return;
    dropBotQr();botQrUrl=URL.createObjectURL(blob);botQrVersion=version;$('bot-qr').src=botQrUrl;$('bot-qr').hidden=false;
  }
}
async function pairBot(replace){await api(`bots/${selectedBotId}/pairing/start`,{replace});await refreshBotPair();}
$('create-bot-form').onsubmit=event=>{event.preventDefault();act(async()=>{
  const created=await api('bots',{name:$('new-bot-name').value.trim(),platform:$('new-bot-platform').value});
  $('new-bot-name').value='';await loadBots();await openBot(created.id);
});};
$('refresh-bots').onclick=()=>act(loadBots);
$('close-bot-detail').onclick=()=>{selectedBotId=null;$('bot-detail').hidden=true;dropBotQr();};
$('rename-bot-form').onsubmit=event=>{event.preventDefault();act(async()=>{
  const bot=botRecords.find(bot=>bot.id===selectedBotId);await api(`bots/${bot.id}`,{name:$('rename-bot-name').value.trim(),enabled:!!bot.enabled});
  await loadBots();$('bot-detail-title').textContent=botName(bot.id);
});};
$('bot-pair-start').onclick=()=>{
  const bound=botRecords.find(bot=>bot.id===selectedBotId)?.status.bound;
  if(bound){$('bot-rebind-confirm').hidden=false;return;}act(()=>pairBot(false));
};
$('bot-rebind-yes').onclick=()=>{$('bot-rebind-confirm').hidden=true;act(()=>pairBot(true));};
$('bot-rebind-no').onclick=()=>{$('bot-rebind-confirm').hidden=true;};
$('bot-pair-cancel').onclick=()=>act(async()=>{await api(`bots/${selectedBotId}/pairing/cancel`,{session_id:botPair.session_id});await refreshBotPair();});
$('bot-verify-form').onsubmit=event=>{event.preventDefault();const code=$('bot-verify-code').value.trim();$('bot-verify-code').value='';
  act(async()=>{await api(`bots/${selectedBotId}/pairing/verify`,{session_id:botPair.session_id,code});await refreshBotPair();});};
async function openBotGrants(client){
  const current=generation;const scope=await api(`clients/${client.id}/bots`);if(current!==generation||!key)return;
  grantClient=client.id;$('key-bot-title').textContent=`Bot 权限 · ${client.name}`;
  drawGrants($('edit-bot-grants'),$('edit-default-bot'),scope.bot_ids,scope.default_bot_id);
  $('key-bot-editor').hidden=false;$('key-bot-editor').scrollIntoView({block:'nearest'});
}
$('key-bot-form').onsubmit=event=>{event.preventDefault();if(!grantClient)return;const id=grantClient;
  const scope={bot_ids:[...$('edit-bot-grants').querySelectorAll('input:checked')].map(input=>input.value),default_bot_id:$('edit-default-bot').value||null};
  act(async()=>{await api(`clients/${id}/bots`,scope);grantClient=null;$('key-bot-editor').hidden=true;await loadClients();});};
$('cancel-key-bots').onclick=()=>{grantClient=null;$('key-bot-editor').hidden=true;};
