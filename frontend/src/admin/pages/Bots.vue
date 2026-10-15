<script setup>
import { ref, computed } from "vue";
import { ElMessageBox } from "element-plus";
import { session, api, run, refresh, copy } from "../session.js";
import { platformName, connectionLabels, date } from "../../shared/format.js";
import { stateLabel } from "../delivery-state.js";
import { confirmConnectionChange } from "../connection-impact.js";
import BotWizard from "../components/BotWizard.vue";
const search = ref(""),
  platform = ref(""),
  wizard = ref(),
  selected = ref(null);
const rows = computed(() =>
  session.bots.filter(
    (b) =>
      (!platform.value || b.platform === platform.value) &&
      (b.name + " " + b.id).toLowerCase().includes(search.value.toLowerCase()),
  ),
);
async function rename(bot) {
  try {
    const r = await ElMessageBox.prompt(
      "只修改站内显示名称，通信身份保持不变。",
      "修改连接名称",
      {
        inputValue: bot.name,
        confirmButtonText: "保存",
        cancelButtonText: "取消",
      },
    );
    await run(async () => {
      await api("bots/" + bot.id, {
        name: r.value.trim(),
        enabled: bot.enabled,
      });
      await refresh();
    });
  } catch (e) {
    if (!["cancel", "close"].includes(e)) session.error = e.message;
  }
}
async function change(bot, kind) {
  await run(async () => {
    if (
      (kind === "delete" || bot.enabled) &&
      !(await confirmConnectionChange(bot, kind === "delete" ? "删除" : "停用"))
    )
      return;
    await api(
      "bots/" + bot.id + (kind === "delete" ? "/delete" : ""),
      kind === "delete" ? {} : { name: bot.name, enabled: !bot.enabled },
    );
    await refresh();
  });
}
async function test(bot) {
  await run(async () => {
    await api("bots/" + bot.id + "/test", {});
    await refresh();
  });
}
async function impact(bot) {
  const result = await run(() => api("bots/" + bot.id + "/impact"));
  if (result) selected.value = { ...result, bot };
}
async function copyCallback(bot) {
  await copy(
    bot.status.callback_url ||
      new URL("../channels/feishu/" + bot.id + "/callback", location.href).href,
  );
}
</script>
<template>
  <div class="stats">
    <el-card
      v-for="[label, value] in [
        ['全部连接', session.bots.length],
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
        <p class="help">配置保存、平台发送、本人的回程回复分别验证。</p>
      </div>
      <el-button type="primary" @click="wizard.open()">新增通信连接</el-button>
    </div>
    <div class="filters">
      <el-input
        v-model="search"
        clearable
        placeholder="搜索名称或连接 ID"
        aria-label="搜索通信连接"
      /><el-select
        v-model="platform"
        clearable
        placeholder="全部平台"
        aria-label="筛选通信平台"
        ><el-option label="微信" value="wechat" /><el-option
          label="飞书"
          value="feishu" /></el-select
      ><el-button :loading="session.busy" @click="run(refresh)">刷新</el-button>
    </div>
    <div>
      <article v-for="bot in rows" :key="bot.id" class="bot-row">
        <div class="bot-avatar" :class="bot.platform">
          {{ bot.platform === "wechat" ? "微" : "飞" }}
        </div>
        <div class="bot-info">
          <h3>
            {{ bot.name
            }}<el-tag
              size="small"
              :type="
                bot.configuration_state === 'pending_configuration'
                  ? 'warning'
                  : bot.enabled
                    ? 'success'
                    : 'info'
              "
              >{{
                bot.configuration_state === "pending_configuration"
                  ? "待配置 · 不可投递"
                  : bot.enabled
                    ? "已启用"
                    : "已停用"
              }}</el-tag
            ><el-tag v-if="bot.recovery_bound" size="small" type="warning">{{
              bot.last_recovery_protected
                ? "最后恢复连接 · 受保护"
                : "管理员恢复连接"
            }}</el-tag>
          </h3>
          <p>
            {{ platformName(bot.platform) }} ·
            {{
              bot.platform === "wechat"
                ? bot.configuration_state === "pending_configuration"
                  ? "待扫码绑定"
                  : connectionLabels[bot.status.connection_status]
                : bot.status.configured
                  ? "平台凭据已保存"
                  : "待配置平台应用"
            }}
          </p>
          <p>
            发送测试：{{
              bot.test?.send_status
                ? stateLabel(bot.test.send_status)
                : "未测试"
            }}
            · 本人回程：{{
              bot.test?.receive_confirmed
                ? "已验证"
                : bot.test?.state === "configuration_changed"
                  ? "配置已变，请重测"
                  : bot.test?.state === "expired"
                    ? "测试已到期"
                    : "尚未验证"
            }}
          </p>
          <p class="help" v-if="bot.test?.started_at">
            最近测试 {{ date(bot.test.started_at) }}；仅表示当次证据。
          </p>
          <code>连接 ID：{{ bot.id }}</code>
          <p class="help">{{ bot.applications?.length || 0 }} 个应用获得授权</p>
        </div>
        <div class="actions">
          <el-button
            :disabled="session.busy || !bot.delivery_ready"
            @click="test(bot)"
            >收发测试</el-button
          ><el-button :disabled="session.busy" @click="impact(bot)"
            >影响范围</el-button
          ><el-dropdown
            @command="
              (kind) =>
                kind === 'configure'
                  ? wizard.open(bot)
                  : kind === 'rename'
                    ? rename(bot)
                    : kind === 'callback'
                      ? copyCallback(bot)
                      : change(bot, kind)
            "
            ><el-button :disabled="session.busy">管理连接 ▾</el-button
            ><template #dropdown
              ><el-dropdown-menu
                ><el-dropdown-item command="configure">{{
                  bot.configuration_state === "pending_configuration"
                    ? "继续配置"
                    : "配置连接"
                }}</el-dropdown-item
                ><el-dropdown-item command="rename">修改名称</el-dropdown-item
                ><el-dropdown-item
                  v-if="bot.platform === 'feishu'"
                  command="callback"
                  >复制回调地址</el-dropdown-item
                ><el-dropdown-item
                  command="enabled"
                  :disabled="
                    (bot.enabled && bot.last_recovery_protected) ||
                    (!bot.enabled &&
                      bot.configuration_state === 'pending_configuration')
                  "
                  >{{ bot.enabled ? "停用连接" : "启用连接" }}</el-dropdown-item
                ><el-dropdown-item
                  command="delete"
                  divided
                  :disabled="bot.last_recovery_protected"
                  >永久删除连接</el-dropdown-item
                ></el-dropdown-menu
              ></template
            ></el-dropdown
          >
        </div>
      </article>
      <el-empty v-if="!rows.length" description="没有匹配的通信连接" />
    </div>
    <el-alert
      title="点击收发测试后，查看本人手机收到的测试通知，将其中一行原样回复给 Bot。配置保存或平台已接收，都不等于回程验证通过。"
      type="info"
      :closable="false" /></el-card
  ><BotWizard ref="wizard" />
  <el-dialog
    :model-value="!!selected"
    title="通信连接的影响范围"
    width="600px"
    @close="selected = null"
    ><template v-if="selected"
      ><h3>{{ selected.bot.name }}</h3>
      <el-alert
        v-if="selected.last_recovery_protected"
        title="最后一个已验证的管理员恢复连接，后端禁止停用、删除和重绑。先验证另一个恢复连接。"
        type="warning"
        :closable="false"
      /><el-table
        :data="selected.applications"
        empty-text="没有获得此连接授权的应用"
        ><el-table-column prop="name" label="应用" /><el-table-column
          label="默认路由"
          ><template #default="{ row }">{{
            row.is_default ? "默认连接" : "调用时选择"
          }}</template></el-table-column
        ><el-table-column label="应用状态"
          ><template #default="{ row }">{{
            row.enabled ? "启用" : "停用"
          }}</template></el-table-column
        ></el-table
      >
      <p class="help">
        停用或删除后，上述应用调用此连接将失败；不会自动改发其他平台。
      </p></template
    ></el-dialog
  >
</template>
