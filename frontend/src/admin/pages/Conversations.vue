<script setup>
import { ref, onMounted, onBeforeUnmount } from "vue";
import { api, run, session } from "../session.js";
import Markdown from "../../shared/Markdown.vue";
import { date } from "../../shared/format.js";
import { stateLabel } from "../delivery-state.js";
const data = ref(null),
  history = ref(null),
  q = ref(""),
  client = ref(""),
  cid = ref(""),
  offset = ref(0),
  anchor = ref(0);
let generation = 0;
async function select(id, around = 0) {
  cid.value = id;
  const g = ++generation;
  await run(async () => {
    const result = await api(
      "conversations/" +
        encodeURIComponent(id) +
        "/messages?" +
        new URLSearchParams({ around }),
    );
    if (g === generation) {
      history.value = result;
      anchor.value = around;
    }
  });
}
async function load() {
  await run(async () => {
    data.value = await api(
      "conversations?" +
        new URLSearchParams({
          q: q.value,
          client_id: client.value,
          offset: offset.value,
        }),
    );
  });
}
async function older() {
  await run(async () => {
    const result = await api(
      "conversations/" +
        cid.value +
        "/messages?before=" +
        history.value.messages[0].id,
    );
    history.value.messages = [...result.messages, ...history.value.messages];
    history.value.has_older = result.has_older;
  });
}
function fromHash() {
  const p = new URLSearchParams(location.hash.split("?")[1] || "");
  if (p.get("c")) select(p.get("c"), Number(p.get("m") || 0));
}
onMounted(async () => {
  await load();
  fromHash();
  window.addEventListener("hashchange", fromHash);
});
onBeforeUnmount(() => {
  generation++;
  window.removeEventListener("hashchange", fromHash);
});
</script>
<template>
  <el-card shadow="never"
    ><form
      class="filters"
      @submit.prevent="
        offset = 0;
        load();
      "
    >
      <el-input
        v-model="q"
        aria-label="搜索会话"
        placeholder="会话、应用或会话 ID"
        clearable
      /><el-select
        v-model="client"
        clearable
        placeholder="所有应用"
        aria-label="会话所属应用"
        ><el-option
          v-for="a in session.clients"
          :key="a.id"
          :label="a.name"
          :value="a.id" /></el-select
      ><el-button native-type="submit" :loading="session.busy">查询</el-button>
    </form>
    <div class="conversation-layout">
      <div class="conversation-list">
        <el-skeleton v-if="!data" :rows="4" animated /><el-empty
          v-else-if="!data.conversations.length"
          description="没有匹配的会话"
        /><button
          v-for="c in data?.conversations || []"
          :key="c.id"
          class="conversation-item"
          :class="{ selected: cid === c.id }"
          @click="select(c.id)"
        >
          <strong>{{ c.name }}</strong
          ><small
            >{{ c.caller }} ·
            {{ c.active ? "可沟通" : "已归档 / 应用停用" }}</small
          >
          <p>{{ c.last_message?.text?.slice(0, 90) || "暂无已记录消息" }}</p>
        </button>
        <div class="pagination" v-if="data">
          <el-button
            :disabled="offset === 0 || session.busy"
            @click="
              offset -= 30;
              load();
            "
            >上一页</el-button
          ><el-button
            :disabled="offset + 30 >= data.total || session.busy"
            @click="
              offset += 30;
              load();
            "
            >下一页</el-button
          >
        </div>
      </div>
      <section class="conversation-detail">
        <el-empty
          v-if="!history"
          description="选择会话查看完整已记录历史"
        /><template v-else
          ><h2>{{ history.conversation.name }}</h2>
          <p class="help">
            {{ history.conversation.caller }} · 仅包含中转站已记录的消息
          </p>
          <el-button
            v-if="history.has_older"
            :loading="session.busy"
            @click="older"
            >加载更早记录</el-button
          >
          <article
            v-for="m in history.messages"
            :key="m.id"
            class="ledger-message"
            :class="{ anchored: anchor === m.id }"
          >
            <div class="message-meta">
              <strong>{{
                m.role === "assistant"
                  ? "接入应用"
                  : m.source === "admin"
                    ? "管理员"
                    : "用户"
              }}</strong
              ><span>{{ date(m.created_at) }} · #{{ m.id }}</span>
            </div>
            <Markdown :text="m.text || ''" />
            <p class="help">{{ stateLabel(m.status) }}</p>
          </article>
          <el-empty
            v-if="!history.messages.length"
            description="暂无已记录消息"
        /></template>
      </section></div
  ></el-card>
</template>
