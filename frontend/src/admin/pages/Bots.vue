<script setup>
import { ref, computed } from "vue";
import { ElMessageBox } from "element-plus";
import { session, api, run, refresh, copy } from "../session.js";
import { platformName, connectionLabels } from "../../shared/format.js";
import BotWizard from "../components/BotWizard.vue";
const search = ref(""),
  platform = ref(""),
  wizard = ref();
const rows = computed(() =>
  session.bots.filter(
    (b) =>
      (!platform.value || b.platform === platform.value) &&
      `${b.name} ${b.id}`.toLowerCase().includes(search.value.toLowerCase()),
  ),
);
async function rename(bot) {
  try {
    const { value } = await ElMessageBox.prompt(
      "只修改通知桥中的显示名称。",
      "修改 Bot 名称",
      {
        inputValue: bot.name,
        inputValidator: (v) =>
          (!!v?.trim() && v.trim().length <= 40) || "请输入 1–40 个字符",
        confirmButtonText: "保存",
        cancelButtonText: "取消",
      },
    );
    await run(async () => {
      await api(`bots/${bot.id}`, { name: value.trim(), enabled: bot.enabled });
      await refresh();
    });
  } catch {}
}
async function remove(bot) {
  try {
    await ElMessageBox.confirm(
      `删除“${bot.name}”后将断开连接，并移除凭据及关联授权。\n历史消息保留，平台机器人不受影响。\n此操作不可撤销。`,
      "删除 Bot",
      {
        type: "warning",
        confirmButtonText: "删除 Bot",
        confirmButtonClass: "el-button--danger",
        cancelButtonText: "取消",
      },
    );
    await run(async () => {
      await api(`bots/${bot.id}/delete`, {});
      await refresh();
    });
  } catch {}
}
async function copyCallback(bot) {
  await copy(
    bot.status.callback_url ||
      new URL(`../channels/feishu/${bot.id}/callback`, location.href).href,
  );
}
</script>
<template>
  <div class="stats">
    <el-card
      v-for="[label, value] in [
        ['全部 Bot', session.bots.length],
        ['微信', session.bots.filter((b) => b.platform === 'wechat').length],
        ['飞书', session.bots.filter((b) => b.platform === 'feishu').length],
        ['已启用', session.bots.filter((b) => b.enabled).length],
      ]"
      :key="label"
      shadow="never"
      ><span>{{ label }}</span
      ><strong>{{ value }}</strong></el-card
    >
  </div>
  <el-card shadow="never"
    ><div class="section-toolbar">
      <div>
        <h2>通信连接</h2>
        <p class="help">管理每个 Bot 的连接、凭据和收发状态。</p>
      </div>
      <el-button type="primary" @click="wizard.open()">新增 Bot</el-button>
    </div>
    <div class="filters">
      <el-input
        v-model="search"
        clearable
        placeholder="搜索名称或 Bot ID"
        aria-label="搜索 Bot"
      /><el-select
        v-model="platform"
        clearable
        placeholder="全部平台"
        aria-label="筛选平台"
        ><el-option label="微信" value="wechat" /><el-option
          label="飞书"
          value="feishu" /></el-select
      ><el-button :loading="session.busy" @click="run(refresh)">刷新</el-button>
    </div>
    <div class="bot-cards">
      <article v-for="bot in rows" :key="bot.id" class="bot-row">
        <div class="bot-avatar" :class="bot.platform">
          {{ bot.platform === "wechat" ? "微" : "飞" }}
        </div>
        <div class="bot-info">
          <h3>
            {{ bot.name }}
            <el-tag size="small" :type="bot.enabled ? 'success' : 'info'">{{
              bot.enabled ? "已启用" : "已停用"
            }}</el-tag>
          </h3>
          <p>
            {{ platformName(bot.platform) }} ·
            {{
              bot.platform === "wechat"
                ? connectionLabels[bot.status.connection_status]
                : bot.status.configured
                  ? "凭据已保存"
                  : "待配置应用"
            }}
          </p>
          <code>bot_id: {{ bot.id }}</code>
        </div>
        <div class="actions">
          <el-button
            v-if="bot.platform === 'feishu'"
            text
            :disabled="session.busy"
            @click="copyCallback(bot)"
            >复制回调地址</el-button
          >
          <el-button
            text
            type="danger"
            :disabled="session.busy"
            @click="remove(bot)"
            >删除</el-button
          >
          <el-button
            type="primary"
            plain
            :disabled="session.busy"
            @click="run(() => wizard.open(bot))"
            >配置 Bot</el-button
          ><el-button text :disabled="session.busy" @click="rename(bot)"
            >改名</el-button
          ><el-button
            text
            :disabled="session.busy"
            @click="
              run(async () => {
                await api(`bots/${bot.id}`, {
                  name: bot.name,
                  enabled: !bot.enabled,
                });
                await refresh();
              })
            "
            >{{ bot.enabled ? "停用" : "启用" }}</el-button
          >
        </div>
      </article>
      <el-empty
        v-if="!rows.length"
        description="没有符合条件的 Bot"
      /></div></el-card
  ><BotWizard ref="wizard" />
</template>
