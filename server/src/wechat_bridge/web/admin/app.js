'use strict';
const $ = id => document.getElementById(id);
let key = '', state = null, busy = false, updating = false, generation = 0;
let qrUrl = '', qrVersion = '', timer = null;
let clients = [], selectedClient = null, lastClientsAt = 0;
const labels = {
  unbound: ['等待绑定', '生成二维码后，用手机微信扫一扫。'],
  waiting_message: ['等待首条消息', '绑定已保存。请在手机 ClawBot 对话发送一句“测试”。'],
  connected: ['微信已连接', '服务正在接收消息，可以通过 MCP 或 API 发送通知。'],
  connecting: ['正在连接', '服务正在检查微信连接，稍后会自动更新。'],
  retrying: ['正在重连', '暂时无法接收消息，服务器会自动重试。'],
  session_expired: ['需要重新绑定', '微信会话已失效，心跳已暂停。请使用原账号重新扫码。']
};
const errors = {
  admin_not_configured: '服务器尚未配置管理员密钥，请按部署说明添加管理员配置后重启。',
  confirm_rebind_required: '已有绑定，请确认后重新绑定。',
  pairing_retry_later: '请稍等几秒再生成二维码。',
  no_verification_pending: '验证码步骤已变化，请按当前提示继续。',
  pairing_session_changed: '连接状态已变化，请刷新状态后再试。',
  invalid_client_name: '名称请使用 1–32 位中英文、数字、下划线或短横线。',
  reserved_client_name: '这个名称由系统保留，请换一个名称。',
  client_exists: '这个客户端名称已存在。原密钥未改变，可在列表中选择“重置密钥”。',
  client_not_found: '该客户端已不存在，请刷新列表。'
};
function showError(message = '') { $('error').textContent = message; $('error').hidden = !message; }
function dropQr() {
  if (qrUrl) URL.revokeObjectURL(qrUrl);
  qrUrl = ''; qrVersion = '';
  $('qr-image').removeAttribute('src'); $('qr-image').hidden = true; $('qr-empty').hidden = false;
}
function logout() {
  $('chat-login-code').hidden = true; $('chat-code-value').value = ''; $('revoke-chat-confirm').hidden = true;
  generation++; key = ''; state = null; clearInterval(timer); timer = null; dropQr();
  $('admin-key').value = ''; $('verify-code').value = '';
  $('rebind-confirm').hidden = true;
  hideIssued(); clients = []; selectedClient = null; lastClientsAt = 0;
  $('client-editor').hidden = true; $('client-rows').replaceChildren(); $('client-name').value = '';
  $('dashboard').hidden = true; $('login').hidden = false; showError();
}
async function api(path, body, binary = false) {
  const headers = {Authorization: `Bearer ${key}`};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(`api/${path}`, {
    method: body === undefined ? 'GET' : 'POST', headers,
    body: body === undefined ? undefined : JSON.stringify(body), cache: 'no-store', credentials: 'omit'
  });
  if (!response.ok) {
    const result = await response.json().catch(() => ({}));
    if (response.status === 401) { logout(); throw new Error('管理员密钥不正确或已失效，请重新输入。'); }
    throw new Error(errors[result.detail] || (response.status === 404 ? '二维码已更新，请稍候。' : '操作暂未完成，请稍后重试。'));
  }
  return binary ? response.blob() : response.json();
}
const date = (value, fallback) => {
  if (!value) return fallback;
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {timeZone:'Asia/Shanghai',
    year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', hourCycle:'h23'})
    .formatToParts(new Date(value * 1000)).map(part => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}`;
};
function render() {
  if (!state) return;
  const s = state.service, p = state.pairing;
  const [title, note] = labels[s.connection_status] || labels.connecting;
  $('status-title').textContent = title; $('connection-note').textContent = note;
  $('connection-dot').className = 'status-dot' + (s.connection_status === 'connected' ? ' connected' : ['retrying','session_expired'].includes(s.connection_status) ? ' warning' : '');
  $('last-activity').textContent = date(s.last_activity_at, '暂无记录');
  $('next-heartbeat').textContent = date(s.next_heartbeat_at, s.connection_status === 'session_expired' ? '已暂停' : '收到首条消息后开始');
  $('last-poll').textContent = date(s.last_poll_success_at, '尚未开始');
  $('inbox-count').textContent = `${s.inbox_count} 条`;
  $('updated-at').textContent = `更新于 ${date(Date.now()/1000)} · 状态每 3 秒更新`;
  $('pair-badge').textContent = p.active ? '绑定进行中' : s.bound ? '已保存绑定' : '尚未绑定';
  $('pair-message').textContent = !p.active && s.context_ready && ['idle','bound'].includes(p.phase) ? '绑定已保存，重启服务后会自动恢复连接。' : p.message;
  $('start-pair').textContent = p.active ? '正在等待连接…' : s.bound ? '重新绑定微信' : '生成二维码';
  $('start-pair').disabled = busy || p.active || !$('rebind-confirm').hidden;
  $('cancel-pair').hidden = !p.active; $('cancel-pair').disabled = busy || p.phase === 'binding';
  $('verify-form').hidden = p.phase !== 'need_verifycode';
  $('rebind-note').hidden = !s.bound;
  $('expiry').hidden = !p.active;
  $('expiry').textContent = `本次连接将在 ${date(p.expires_at, '稍后')} 结束`;
  $('qr-title').textContent = p.active ? (p.phase === 'need_verifycode' ? '填写连接数字' : '正在准备连接') : s.bound ? '微信绑定已保存' : '准备连接你的微信';
  $('qr-description').textContent = s.bound && !p.active ? (s.context_ready ? '无需重复扫码，可在右侧查看连接状态。' : '请前往手机微信发送首条消息。') : '请按照下方提示完成操作。';
  if (!p.qr_available) dropQr();
}
async function refresh() {
  if (updating || !key) return;
  updating = true;
  const current = generation;
  try {
    const result = await api('status');
    if (current !== generation || !key) return;
    state = result; render();
    if (Date.now() - lastClientsAt > 10000) await loadClients();
    const p = state.pairing, version = `${p.session_id}/${p.qr_version}`;
    if (p.qr_available && qrVersion !== version) {
      const blob = await api(`pairing/qr?session_id=${encodeURIComponent(p.session_id)}`, undefined, true);
      if (current !== generation || !key) return;
      dropQr(); qrVersion = version; qrUrl = URL.createObjectURL(blob);
      $('qr-image').src = qrUrl; $('qr-image').hidden = false; $('qr-empty').hidden = true;
    }
  } finally { updating = false; }
}
async function act(action) {
  if (busy) return;
  busy = true; showError(); render();
  for (const button of $('verify-form').querySelectorAll('button')) button.disabled = true;
  try { await action(); await refresh(); }
  catch (error) { showError(error instanceof TypeError ? '无法连接服务器，请检查网络后重试。' : error.message); }
  finally { busy = false; render(); for (const button of $('verify-form').querySelectorAll('button')) button.disabled = false; }
}
$('login-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy) return;
  key = $('admin-key').value.trim(); $('admin-key').value = ''; generation++;
  $('login-button').disabled = true;
  await act(async () => {
    await refresh();
    if (!state) throw new Error('连接状态暂未加载，请重新输入密钥。');
    $('login').hidden = true; $('dashboard').hidden = false;
    clearInterval(timer); timer = setInterval(() => { if (!busy) refresh().catch(error => showError(error instanceof TypeError ? '连接中断，正在等待服务器恢复。' : error.message)); }, 3000);
  });
  $('login-button').disabled = false;
});
$('logout').addEventListener('click', logout);
$('start-pair').addEventListener('click', () => {
  if (!state) return;
  const replace = state.service.bound;
  if (replace) { $('rebind-confirm').hidden = false; render(); return; }
  act(() => api('pairing/start', {replace}));
});
$('confirm-rebind').addEventListener('click', () => {
  $('rebind-confirm').hidden = true;
  act(() => api('pairing/start', {replace:true}));
});
$('keep-binding').addEventListener('click', () => { $('rebind-confirm').hidden = true; render(); });
$('cancel-pair').addEventListener('click', () => act(() => api('pairing/cancel', {session_id: state.pairing.session_id})));
$('verify-form').addEventListener('submit', event => {
  event.preventDefault(); const code = $('verify-code').value.trim(); $('verify-code').value = '';
  act(() => api('pairing/verify', {session_id: state.pairing.session_id, code}));
});
window.addEventListener('pagehide', logout);

function hideIssued() {
  $('issued-key').hidden = true; $('key-value').value = ''; $('client-config').value = ''; $('issued-note').textContent = '';
}
function showIssued(result) {
  if (!key) return;
  $('key-value').value = result.api_key;
  $('client-config').value = JSON.stringify({base_url:result.base_url || 'https://你的服务器/wechat', api_key:result.api_key}, null, 2);
  $('issued-note').textContent = `客户端：[${result.client.name}]。重置后，旧密钥立即失效。`;
  $('issued-key').hidden = false;
}
async function loadClients() {
  const current = generation, result = await api('clients');
  if (current !== generation || !key) return;
  lastClientsAt = Date.now();
  if (JSON.stringify(clients) === JSON.stringify(result.clients)) return;
  clients = result.clients;
  $('clients-empty').hidden = clients.length > 0; $('clients-table').hidden = !clients.length;
  const rows = clients.map(client => {
    const row = document.createElement('tr');
    for (const text of [`[${client.name}]`, client.enabled ? '启用' : '停用', date(client.last_seen_at, '尚未调用')]) {
      const cell = document.createElement('td'); cell.textContent = text; row.append(cell);
    }
    const actions = document.createElement('td'); actions.className = 'client-actions';
    for (const [action, label] of [['rename','改名'], ['rotate',client.enabled ? '重置密钥' : '重新启用'], ['revoke','停用'], ['delete','删除密钥']]) {
      if (action === 'revoke' && !client.enabled) continue;
      const button = document.createElement('button'); button.type = 'button'; button.className = 'text-button';
      if (action === 'delete') button.classList.add('danger-text');
      button.textContent = label; button.addEventListener('click', () => openClientEditor(client, action)); actions.append(button);
    }
    row.append(actions); return row;
  });
  $('client-rows').replaceChildren(...rows);
}
function openClientEditor(client, action) {
  selectedClient = {id:client.id, name:client.name, action}; hideIssued();
  const titles = {rename:'修改名称', rotate:'重置密钥', revoke:'停用客户端', delete:'删除密钥'};
  const notes = {
    rename:'修改消息中的来源标记，原密钥仍有效。',
    rotate:'旧密钥会立即失效，并生成一把新密钥。需要重新配置这个客户端。',
    revoke:'停用后，该密钥将无法调用服务。其他客户端不受影响。',
    delete:'确认后将删除这个客户端及其密钥，旧密钥立即失效，无法恢复。历史消息和其他客户端会保留；以后可用同名重新创建新密钥。'
  };
  $('editor-title').textContent = `${titles[action]} · [${client.name}]`;
  $('editor-note').textContent = notes[action];
  $('rename-field').hidden = action !== 'rename'; $('rename-client').required = action === 'rename';
  $('rename-client').value = client.name; $('client-editor').hidden = false;
  $('confirm-client-action').textContent = {rename:'保存名称', rotate:'生成新密钥', revoke:'确认停用', delete:'确认删除密钥'}[action];
  $('confirm-client-action').classList.toggle('danger', action === 'delete');
  $('client-editor').scrollIntoView({block:'nearest'});
}
$('create-client-form').addEventListener('submit', event => {
  event.preventDefault(); const name = $('client-name').value.trim();
  act(async () => {
    hideIssued(); const result = await api('clients', {name}); showIssued(result);
    $('client-name').value = ''; $('client-result').textContent = `已创建 [${result.client.name}]。`;
    await loadClients();
  });
});
$('edit-client-form').addEventListener('submit', event => {
  event.preventDefault(); if (!selectedClient) return;
  const selection = {...selectedClient}, name = $('rename-client').value.trim();
  act(async () => {
    const result = await api(`clients/${encodeURIComponent(selection.id)}/${selection.action}`, selection.action === 'rename' ? {name} : {});
    $('client-editor').hidden = true; selectedClient = null;
    if (result.api_key) showIssued(result);
    $('client-result').textContent = selection.action === 'delete' ? `已删除 [${result.client.name}] 的密钥，旧密钥已失效。` : `已更新 [${result.client.name}]。`;
    await loadClients();
  });
});
$('cancel-client-action').addEventListener('click', () => { selectedClient = null; $('client-editor').hidden = true; });
$('dismiss-key').addEventListener('click', hideIssued);
$('refresh-clients').addEventListener('click', () => act(loadClients));

$('issue-chat-code').onclick = async () => {
  const button = $('issue-chat-code'), current = generation;
  button.disabled = true;
  try { const result = await api('chat/login-code', {}); if (current !== generation) return;
    $('chat-code-value').value = result.code; $('chat-login-code').hidden = false;
    $('chat-access-result').textContent = '登录码已生成，10 分钟内有效。';
    setTimeout(() => { if ($('chat-code-value').value === result.code) { $('chat-code-value').value = ''; $('chat-login-code').hidden = true; } }, 600000);
  } catch (e) { showError(e.message); } finally { button.disabled = false; }
};
$('revoke-chat-sessions').onclick = () => { $('revoke-chat-confirm').hidden = false; };
$('cancel-chat-revoke').onclick = () => { $('revoke-chat-confirm').hidden = true; };
$('confirm-chat-revoke').onclick = async () => {
  try { await api('chat/revoke-sessions', {}); $('revoke-chat-confirm').hidden = true;
    $('chat-login-code').hidden = true; $('chat-code-value').value = ''; $('chat-access-result').textContent = '已退出所有手机登录。';
  } catch (e) { showError(e.message); }
};
