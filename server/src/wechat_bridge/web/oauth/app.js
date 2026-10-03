'use strict';
const $=id=>document.getElementById(id), request_id=new URL(location.href).searchParams.get('request');
async function api(path, body){
 const r=await fetch(path,{method:body?'POST':'GET',credentials:'same-origin',headers:body?{'Content-Type':'application/json','X-Chat-Request':'1'}:{},body:body?JSON.stringify(body):undefined});
 if(r.status===401){$('login').hidden=false;$('consent').hidden=true;throw new Error('请先登录');}
 if(!r.ok)throw new Error(r.status===410?'连接请求已过期，请回到插件重新连接':'请求失败，请稍后重试');
 return r.json();
}
async function load(){try{
 const info=await api('request?request_id='+encodeURIComponent(request_id));
 $('login').hidden=true;$('consent').hidden=false;$('status').textContent=info.client_name+' 请求连接';
 $('callback').textContent='授权后返回：'+new URL(info.redirect_uri).origin;
 $('client').replaceChildren(...info.clients.map(c=>{const o=document.createElement('option');o.value=c.id;o.textContent=c.name;return o;}));
 $('allow').disabled=!info.clients.length;
}catch(e){$('status').textContent=e.message;}}
$('login').onsubmit=async e=>{e.preventDefault();try{await api('../api/login',{code:$('code').value});$('code').value='';await load();}catch(e){$('status').textContent=e.message;}};
async function consent(allow){$('allow').disabled=$('deny').disabled=true;try{
 const result=await api('consent',{request_id,api_client:$('client').value,allow});location.assign(result.redirect);
}catch(e){$('status').textContent=e.message;$('allow').disabled=$('deny').disabled=false;}}
$('allow').onclick=()=>consent(true);$('deny').onclick=()=>consent(false);load();
