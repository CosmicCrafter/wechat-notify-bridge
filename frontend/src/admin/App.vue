<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from "vue";
import {
  Connection,
  Key,
  Switch,
  ChatLineRound,
  Document,
  ArrowRight,
} from "@element-plus/icons-vue";
import { session, logout, run, refresh } from "./session.js";
import Bots from "./pages/Bots.vue";
import Keys from "./pages/Keys.vue";
import Proxy from "./pages/Proxy.vue";
import Sessions from "./pages/Sessions.vue";
import Developer from "./pages/Developer.vue";
const navigation = [
  ["bots", "Bot 管理", Connection],
  ["keys", "接入密钥", Key],
  ["proxy", "代理设置", Switch],
  ["sessions", "会话登录", ChatLineRound],
  ["developer", "开发者文档", Document],
];
const pages = {
  bots: Bots,
  keys: Keys,
  proxy: Proxy,
  sessions: Sessions,
  developer: Developer,
};
const page = ref("bots"),
  loginKey = ref("");
let timer,
  refreshing = false;
function route() {
  let name = location.hash.slice(1);
  name =
    { nodes: "proxy", subscription: "proxy", feishu: "bots", overview: "bots" }[
      name
    ] || name;
  page.value = pages[name] ? name : "bots";
  document.title = "通知桥 · " + navigation.find((n) => n[0] === page.value)[1];
}
function navigate(name) {
  location.hash = name;
}
async function login() {
  await run(async () => {
    session.key = loginKey.value.trim();
    loginKey.value = "";
    session.epoch++;
    await refresh();
    session.authenticated = true;
  });
}
async function poll() {
  if (!session.authenticated || session.busy || refreshing || document.hidden)
    return;
  refreshing = true;
  try {
    await refresh();
  } catch (e) {
    if (!e.stale) session.error = e.message;
  } finally {
    refreshing = false;
  }
}
onMounted(() => {
  route();
  window.addEventListener("hashchange", route);
  window.addEventListener("pagehide", logout);
  timer = setInterval(poll, 10000);
});
onBeforeUnmount(() => {
  clearInterval(timer);
  window.removeEventListener("hashchange", route);
  window.removeEventListener("pagehide", logout);
  logout();
});
const title = computed(() => navigation.find((n) => n[0] === page.value)[1]);
</script>
<template>
  <el-config-provider
    ><div v-if="!session.authenticated" class="login-page">
      <div class="login-brand">↗</div>
      <h1>通知桥</h1>
      <p>连接你的程序与消息平台</p>
      <el-card shadow="never" class="login-card"
        ><h2>登录管理中心</h2>
        <p class="help">使用部署时设置的管理员密钥，非程序调用密钥。</p>
        <el-form label-position="top" @submit.prevent="login"
          ><el-form-item label="管理员密钥"
            ><el-input
              v-model="loginKey"
              type="password"
              show-password
              autocomplete="off"
              placeholder="请输入管理员密钥" /></el-form-item
          ><el-button
            type="primary"
            native-type="submit"
            :loading="session.busy"
            class="full"
            >进入管理中心</el-button
          ></el-form
        ><el-alert
          v-if="session.error"
          :title="session.error"
          type="error"
          :closable="false"
        />
        <p class="help">
          密钥只保存在当前页面内存中，刷新后需重新登录。
        </p></el-card
      >
    </div>
    <div v-else class="admin-shell">
      <aside class="sidebar">
        <div class="brand">
          <span>↗</span>
          <div><strong>通知桥</strong><small>Notify Bridge</small></div>
        </div>
        <p class="nav-label">工作空间</p>
        <el-menu :default-active="page" @select="navigate"
          ><el-menu-item
            v-for="[id, label, icon] in navigation"
            :key="id"
            :index="id"
            ><el-icon><component :is="icon" /></el-icon
            ><span>{{ label }}</span></el-menu-item
          ></el-menu
        >
        <div class="sidebar-bottom">
          <el-tag type="success" effect="plain">管理员已登录</el-tag
          ><el-button text @click="logout">退出登录</el-button>
        </div>
      </aside>
      <div class="main-shell">
        <header class="topbar">
          <span
            >工作空间 <el-icon><ArrowRight /></el-icon> {{ title }}</span
          ><el-link href="../chat/" target="_blank">会话页 ↗</el-link>
        </header>
        <main class="page-content">
          <div class="page-heading">
            <h1>{{ title }}</h1>
            <p>统一连接，专注沟通。</p>
          </div>
          <el-alert
            v-if="session.error"
            :title="session.error"
            type="error"
            show-icon
            @close="session.error = ''"
          /><component :is="pages[page]" :key="page" />
        </main>
      </div></div
  ></el-config-provider>
</template>
