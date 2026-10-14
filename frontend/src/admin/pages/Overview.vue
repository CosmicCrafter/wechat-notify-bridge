<script setup>
import { ref, onMounted } from "vue";
import { api, run } from "../session.js";
const data = ref(null);
function go(target) {
  location.hash = target;
}
async function load() {
  await run(async () => {
    data.value = await api("overview");
  });
}
onMounted(load);
</script>
<template>
  <div v-if="data">
    <div class="stats">
      <el-card
        shadow="never"
        v-for="[label, value, target] in [
          ['接入应用', data.applications, 'keys'],
          ['待处理任务', data.counts.pending_tasks, 'conversations'],
          ['24 小时失败', data.counts.failed, 'deliveries'],
          ['24 小时结果未知', data.counts.unknown, 'deliveries'],
        ]"
        :key="label"
        ><span>{{ label }}</span
        ><strong>{{ value }}</strong
        ><el-button link type="primary" @click="go(target)"
          >查看 →</el-button
        ></el-card
      >
    </div>
    <el-card shadow="never"
      ><div class="section-toolbar">
        <h2>最近会话</h2>
        <el-button text @click="load">刷新</el-button>
      </div>
      <el-empty
        v-if="!data.conversations.length"
        description="还没有已记录的会话"
      />
      <div v-for="c in data.conversations" :key="c.id" class="summary-row">
        <div>
          <strong>{{ c.name }}</strong>
          <p class="help">
            {{ c.caller }} ·
            {{ c.last_message?.text?.slice(0, 120) || "暂无消息" }}
          </p>
        </div>
        <el-button @click="go('conversations?c=' + encodeURIComponent(c.id))"
          >打开会话</el-button
        >
      </div></el-card
    ><el-alert
      title="中转站记录平台响应；平台已接收不等于手机已收到，也不代表应用已处理。"
      type="info"
      :closable="false"
    />
  </div>
  <el-skeleton v-else :rows="6" animated />
</template>
