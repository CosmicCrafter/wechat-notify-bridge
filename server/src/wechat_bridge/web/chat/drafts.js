'use strict';
// Replies stay on this browser. Never load them before owner authentication.
const browserDrafts={key:null,entries:{},failed:false,
  open(scope){const key='wechat-drafts-v1:'+scope;if(this.key===key)return false;this.key=key;this.entries={};try{const value=JSON.parse(localStorage.getItem(key)||'{}');if(value&&typeof value==='object'&&!Array.isArray(value))for(const [id,item] of Object.entries(value))if(item&&Date.now()-item.at<30*86400000)this.entries[id]=item;}catch{}return true;},
  get(id){return this.entries[id]?.value;},
  set(id,value){if(!this.key)return;try{const latest=JSON.parse(localStorage.getItem(this.key)||'{}');if(latest&&typeof latest==='object'&&!Array.isArray(latest))this.entries=latest;}catch{}for(const [name,item] of Object.entries(this.entries))if(!item||Date.now()-item.at>=30*86400000)delete this.entries[name];if(value===null)delete this.entries[id];else this.entries[id]={at:Date.now(),value};try{localStorage.setItem(this.key,JSON.stringify(this.entries));this.failed=false;}catch{this.failed=true;}},
  clear(){if(this.key)try{localStorage.removeItem(this.key);}catch{}this.key=null;this.entries={};this.failed=false;}
};
