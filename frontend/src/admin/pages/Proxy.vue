<script setup>
import { ref, reactive, onMounted, onBeforeUnmount, computed } from "vue";
import { api, run, session } from "../session.js";
import { date } from "../../shared/format.js";
import { errors } from "../../shared/errors.js";
const state = ref(null),
  node = ref(""),
  dirty = ref(false),
  form = reactive({
    subscription_url: "",
    enabled: true,
    hours: 6,
    minutes: 5,
    priorities: "",
  });
let timer,
  loaded = false,
  loading = false,
  alive = true;
function apply(p) {
  state.value = p;
  if (!dirty.value) node.value = p.mode === "manual" ? p.manual_node : "";
  if (!loaded) {
    Object.assign(form, {
      hours: p.update_interval / 3600,
      minutes: p.check_interval / 60,
      priorities: p.priorities.join("\n"),
      enabled: p.enabled,
    });
    loaded = true;
  }
}
async function load() {
  if (loading) return;
  loading = true;
  try {
    const p = await api("proxy");
    if (alive) apply(p);
  } finally {
    loading = false;
  }
}
async function operation(path, body) {
  await run(async () => {
    const p = await api("proxy/" + path, body);
    if (!alive) return;
    if (path === "select") dirty.value = false;
    if (path === "config") form.subscription_url = "";
    apply(p);
  });
}
const disabled = computed(
  () => session.busy || !state.value?.available || state.value?.busy,
);
const usage = computed(() => state.value?.usage || {});
const used = computed(
  () => (usage.value.upload || 0) + (usage.value.download || 0),
);
const size = (n) => (n == null ? "—" : (n / 2 ** 30).toFixed(2) + " GiB");
onMounted(() => {
  run(load);
  timer = setInterval(() => {
    if (!session.busy) load().catch(() => {});
  }, 5000);
});
onBeforeUnmount(() => {
  alive = false;
  clearInterval(timer);
});
</script>
<template>
  <el-alert
    title="微信和飞书直连；代理仅用于 Codex / GPT 云端回调。"
    type="info"
    :closable="false"
  /><template v-if="state"
    ><el-card shadow="never"
      ><div class="section-toolbar">
        <div>
          <h2>节点与连接</h2>
          <p class="help">
            {{
              state.mode === "manual" ? "手动固定节点" : "按优先规则自动选择"
            }}
          </p>
        </div>
        <el-button :disabled="disabled" @click="operation('check', {})"
          >测试连接</el-button
        >
      </div>
      <div class="current-node">
        <strong>{{ state.current_node || "尚未选择节点" }}</strong
        ><el-tag
          >{{
            state.nodes.find((n) => n.name === state.current_node)?.delay || "—"
          }}
          ms</el-tag
        >
      </div>
      <el-form label-position="top"
        ><el-form-item label="选择节点"
          ><el-select
            v-model="node"
            filterable
            @change="dirty = true"
            :disabled="disabled"
            ><el-option label="自动按优先规则选择" value="" /><el-option
              v-for="n in state.nodes"
              :key="n.name"
              :value="n.name"
              :label="
                n.name + (n.delay ? ' · ' + n.delay + ' ms' : '')
              " /></el-select></el-form-item
        ><el-button
          type="primary"
          :disabled="disabled"
          @click="operation('select', { name: node || null })"
          >应用选择</el-button
        ></el-form
      >
      <p class="help">
        最近检测：{{ date(state.last_check_at) }} · 优先级：{{
          state.priorities.join(" → ") || "自动选择可用节点"
        }}
      </p>
      <el-alert
        v-if="state.last_error || !state.available"
        :title="
          errors[state.last_error] ||
          '代理管理尚未配置，请先完成服务器端 Mihomo 配置。'
        "
        type="warning"
        :closable="false"
    /></el-card>
    <el-card shadow="never"
      ><div class="section-toolbar">
        <div>
          <h2>代理订阅</h2>
          <p class="help">
            {{ state.subscription_label || "未配置订阅" }} ·
            {{ state.source === "admin" ? "管理页配置" : ".env 初始配置" }}
          </p>
        </div>
        <el-button :disabled="disabled" @click="operation('update', {})"
          >更新订阅</el-button
        >
      </div>
      <el-descriptions :column="2" border
        ><el-descriptions-item label="最近更新">{{
          date(state.last_update_at)
        }}</el-descriptions-item
        ><el-descriptions-item label="下次更新">{{
          state.enabled ? date(state.next_update_at) : "已暂停"
        }}</el-descriptions-item
        ><el-descriptions-item label="已用 / 总量">{{
          usage.total ? size(used) + " / " + size(usage.total) : "订阅未提供"
        }}</el-descriptions-item
        ><el-descriptions-item label="到期时间">{{
          date(usage.expire, "订阅未提供")
        }}</el-descriptions-item></el-descriptions
      ><el-progress
        v-if="usage.total"
        :percentage="Math.min(100, Math.round((used / usage.total) * 100))"
      />
      <el-divider content-position="left">订阅与自动更新</el-divider
      ><el-form label-position="top"
        ><el-form-item label="订阅地址"
          ><el-input
            v-model="form.subscription_url"
            type="password"
            show-password
            placeholder="HTTPS 订阅地址；留空保留已有地址"
          />
          <p class="help">
            订阅地址加密保存，不回显。仅导入 Clash / Mihomo YAML 节点。
          </p></el-form-item
        >
        <div class="form-grid">
          <el-form-item label="订阅更新间隔（小时）"
            ><el-input-number
              v-model="form.hours"
              :min="1"
              :max="168" /></el-form-item
          ><el-form-item label="连接检测间隔（分钟）"
            ><el-input-number v-model="form.minutes" :min="1" :max="60"
          /></el-form-item>
        </div>
        <el-form-item label="节点优先规则"
          ><el-input
            v-model="form.priorities"
            type="textarea"
            :rows="3"
            placeholder="日本 Pro&#10;美国 Pro&#10;新加坡 Pro"
          />
          <p class="help">
            每行一组，按顺序尝试；同组关键词须全部匹配。留空则自动选择可用节点。
          </p></el-form-item
        ><el-form-item
          ><el-switch
            v-model="form.enabled"
            active-text="自动更新订阅与检测连接" /></el-form-item
        ><el-button
          type="primary"
          :disabled="disabled"
          @click="
            operation('config', {
              subscription_url: form.subscription_url.trim() || null,
              enabled: form.enabled,
              update_interval: form.hours * 3600,
              check_interval: form.minutes * 60,
              priorities: form.priorities
                .split('\n')
                .map((s) => s.trim())
                .filter(Boolean),
            })
          "
          >保存设置</el-button
        >
        <p class="help">
          关闭自动管理不会停止代理进程。管理页配置优先于 .env 初始值。
        </p></el-form
      ></el-card
    ></template
  >
</template>
