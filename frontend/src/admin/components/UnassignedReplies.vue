<script setup>
import { ref, onMounted } from "vue";
import { api, run, session } from "../session.js";
import Markdown from "../../shared/Markdown.vue";
import { date } from "../../shared/format.js";
const rows = ref([]),
  choices = ref([]),
  selected = ref({}),
  next = ref(null);
async function search(q = "") {
  choices.value = (
    await api("conversations?q=" + encodeURIComponent(q))
  ).conversations.filter((c) => c.can_reply);
}
async function load(append = false) {
  const result = await api(
    "unassigned" + (append ? "?after=" + next.value : ""),
  );
  rows.value = append ? [...rows.value, ...result.messages] : result.messages;
  next.value = result.next_after;
}
async function assign(row) {
  if (!selected.value[row.id]) return;
  await run(async () => {
    await api("unassigned/" + row.id + "/assign", {
      conversation_id: selected.value[row.id],
    });
    await load();
  });
}
onMounted(() =>
  run(async () => {
    await load();
    await search();
  }),
);
</script>
<template>
  <div>
    <p class="help">
      无明确引用的回复不会自动交给最近会话或唯一待填任务。请核对来源后选择会话。
    </p>
    <el-button :loading="session.busy" @click="run(() => load())"
      >刷新待归属消息</el-button
    ><el-empty v-if="!rows.length" description="没有待归属消息" /><el-card
      v-for="row in rows"
      :key="row.id"
      shadow="never"
      ><div class="section-toolbar">
        <strong
          >{{ row.source === "feishu" ? "飞书" : "微信" }} · #{{
            row.id
          }}</strong
        ><time>{{ date(row.received_at) }}</time>
      </div>
      <Markdown :text="row.text || ''" />
      <div class="actions">
        <el-select
          v-model="selected[row.id]"
          filterable
          remote
          :remote-method="
            (q) => search(q).catch((e) => (session.error = e.message))
          "
          placeholder="按名称或会话 ID 搜索"
          aria-label="归属会话"
          ><el-option
            v-for="c in choices"
            :key="c.id"
            :label="c.caller + ' · ' + c.name"
            :value="c.id" /></el-select
        ><el-button
          type="primary"
          :disabled="!selected[row.id]"
          :loading="session.busy"
          @click="assign(row)"
          >确认归属</el-button
        >
      </div></el-card
    ><el-button
      v-if="next"
      :loading="session.busy"
      @click="run(() => load(true))"
      >加载更多</el-button
    >
  </div>
</template>
