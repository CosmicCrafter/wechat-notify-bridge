<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from "vue";
import {
  Connection,
  Key,
  Setting,
  ChatLineRound,
  Document,
  DataAnalysis,
} from "@element-plus/icons-vue";
import { session, logout, run, refresh, restore } from "./session.js";
import Login from "./components/Login.vue";
import Bots from "./pages/Bots.vue";
import Keys from "./pages/Keys.vue";
import Settings from "./pages/Settings.vue";
import Developer from "./pages/Developer.vue";
import Account from "./pages/Account.vue";
import Overview from "./pages/Overview.vue";
import Conversations from "./pages/Conversations.vue";
import Deliveries from "./pages/Deliveries.vue";
const navigation = [
  ["overview", "总览", DataAnalysis],
  ["conversations", "会话中心", ChatLineRound],
  ["deliveries", "投递记录", Document],
  ["keys", "接入应用", Key],
  ["bots", "通信连接", Connection],
  ["settings", "系统设置", Setting],
];
const pages = {
  overview: Overview,
  conversations: Conversations,
  deliveries: Deliveries,
  keys: Keys,
  bots: Bots,
  settings: Settings,
  help: Developer,
  account: Account,
};
const descriptions = {
  overview: "掌握消息流转，及时处理需要关注的事项。",
  conversations: "与接入应用持续沟通，与手机端共享已记录历史。",
  deliveries: "区分平台接收、投递失败与结果未知。",
  keys: "为每个接入程序建立独立身份与授权。",
  bots: "连接微信与飞书，统一管理通信状态。",
  settings: "管理代理、节点与运行设置。",
  help: "部署维护、AI 接入与业务系统接入。",
  account: "管理登录身份与恢复方式。",
};
const page = ref("overview");
let timer,
  refreshing = false;
const title = computed(
  () =>
    navigation.find((n) => n[0] === page.value)?.[1] ||
    { account: "管理员账号", help: "帮助与接入" }[page.value],
);
function route() {
  const name = location.hash.slice(1).split("?")[0];
  page.value = pages[name]
    ? name
    : {
        proxy: "settings",
        nodes: "settings",
        subscription: "settings",
        sessions: "settings",
        developer: "help",
        feishu: "bots",
      }[name] || "overview";
  document.title = "Notify Bridge · " + title.value;
}
function navigate(name) {
  location.hash = name;
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
  restore().catch((e) => {
    session.error = e.message;
  });
  timer = setInterval(poll, 10000);
});
onBeforeUnmount(() => {
  clearInterval(timer);
  window.removeEventListener("hashchange", route);
});
</script>
<template>
  <el-config-provider>
    <div v-if="!session.ready" class="login-page" aria-busy="true">
      <p>正在恢复管理会话…</p>
    </div>
    <Login v-else-if="!session.authenticated" />
    <div v-else class="admin-shell">
      <aside class="sidebar">
        <div class="brand">
          <span>↗</span>
          <div><strong>Notify Bridge</strong><small>统一消息中转站</small></div>
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
          <el-tag effect="plain">统一收发 · 独立授权</el-tag
          ><small class="help">程序接入，平台通信，持续沟通。</small>
        </div>
      </aside>
      <div class="main-shell">
        <header class="topbar">
          <span>{{ title }}</span>
          <div class="actions">
            <el-button text @click="navigate('help')">帮助与接入</el-button
            ><el-dropdown
              @command="
                (command) =>
                  command === 'logout' ? logout() : navigate(command)
              "
              ><el-button text
                >{{ session.account?.username || "管理员" }} ▾</el-button
              ><template #dropdown
                ><el-dropdown-menu
                  ><el-dropdown-item command="account"
                    >账号与安全</el-dropdown-item
                  ><el-dropdown-item command="logout"
                    >退出登录</el-dropdown-item
                  ></el-dropdown-menu
                ></template
              ></el-dropdown
            >
          </div>
        </header>
        <main class="page-content">
          <div class="page-heading">
            <h1>{{ title }}</h1>
            <p>{{ descriptions[page] }}</p>
          </div>
          <el-alert
            v-if="session.error"
            :title="session.error"
            type="error"
            show-icon
            @close="session.error = ''"
          /><component :is="pages[page]" :key="page" />
        </main>
      </div>
    </div>
  </el-config-provider>
</template>
