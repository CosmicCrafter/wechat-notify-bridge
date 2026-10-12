<script setup>
import { ref, onMounted } from "vue";
import { api, run, session } from "../session.js";
import Markdown from "../../shared/Markdown.vue";
import { ElMessage } from "element-plus";
const docs = ref(null),
  tab = ref("guide");
onMounted(() => run(async () => (docs.value = await api("developer-docs"))));
function download() {
  run(async () => {
    const blob = await api("developer-kit", undefined, true),
      url = URL.createObjectURL(blob),
      a = document.createElement("a");
    a.href = url;
    a.download = "notify-bridge-developer-kit.zip";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
    ElMessage.success("下载已开始，从 START-HERE.md 开始阅读。");
  });
}
</script>
<template>
  <el-card shadow="never"
    ><div class="section-toolbar">
      <div>
        <h2>开发者文档</h2>
        <p class="help">接口、MCP 与示例；将通知和交互接入你的程序。</p>
      </div>
      <el-button type="primary" :loading="session.busy" @click="download"
        >下载接入资料包</el-button
      >
    </div>
    <el-tabs v-model="tab"
      ><el-tab-pane label="接入指南" name="guide" /><el-tab-pane
        label="接口文档"
        name="api" /><el-tab-pane label="任务卡片" name="cards" /></el-tabs
    ><Markdown
      v-if="docs"
      :text="docs[tab] || ''"
      :base="
        'https://github.com/CosmicCrafter/wechat-notify-bridge/blob/main/docs/' +
        (tab === 'guide' ? 'integration/' : 'server/')
      "
  /></el-card>
</template>
