<script setup>
import { ref, computed, watch } from "vue";
import { ElMessage } from "element-plus";
import {
  Connection,
  Refresh,
  Setting,
  Warning,
  CircleCheck,
} from "@element-plus/icons-vue";
const props = defineProps({
  state: { type: Object, required: true },
  scenario: { type: String, default: "normal" },
});
const nodeSearch = ref(""),
  selectedMode = ref(props.state.mode),
  selectedNode = ref(props.state.manual_node || ""),
  busy = ref(false),
  configDialog = ref(false),
  helpDialog = ref(false),
  formError = ref(""),
  operationMessage = ref(""),
  generation = ref(0);
const form = ref({
  url: "",
  hours: 6,
  minutes: 5,
  priorities: "",
  enabled: true,
});
const rows = computed(() =>
  props.state.nodes.filter(
    (n) =>
      !nodeSearch.value ||
      n.name.toLowerCase().includes(nodeSearch.value.toLowerCase()),
  ),
);
const locked = computed(
  () => busy.value || !props.state.available || props.state.current_unknown,
);
const changed = computed(
  () =>
    selectedMode.value !== props.state.mode ||
    (selectedMode.value === "manual" &&
      selectedNode.value !== props.state.manual_node),
);
const errors = {
  proxy_update_fail: "订阅下载失败，未替换运行节点与上次可用配置。",
  proxy_no_available_node:
    "当前优先规则内没有可用节点；保留原节点选择，不自动改为直连。",
  proxy_controller_unavailable:
    "无法访问 Mihomo 控制接口，当前实际出口未确认。",
  proxy_rollback_failed:
    "恢复旧配置失败，当前实际出口未确认。停止继续切换或更新，先由管理员检查代理进程。",
  proxy_operation_failed: "连接检测未完成，不能宣称回调可达。",
};
watch(
  () => props.scenario,
  () => {
    generation.value++;
    busy.value = false;
    configDialog.value = false;
    nodeSearch.value = "";
    selectedMode.value = props.state.mode;
    selectedNode.value = props.state.manual_node || "";
    operationMessage.value = "";
  },
);
function openConfig() {
  form.value = {
    url: "",
    hours: props.state.update_hours,
    minutes: props.state.check_minutes,
    priorities: props.state.priorities.join("\n"),
    enabled: props.state.enabled,
  };
  formError.value = "";
  configDialog.value = true;
}
function saveConfig() {
  formError.value = "";
  const f = form.value;
  let label = props.state.subscription_label;
  if (f.url.trim()) {
    try {
      const u = new URL(f.url.trim());
      if (
        u.protocol !== "https:" ||
        u.username ||
        u.password ||
        u.hash ||
        !u.hostname.endsWith(".example.test")
      )
        throw Error();
      label = u.hostname;
    } catch {
      formError.value =
        "原型只接受 example.test 下的 HTTPS 示例地址，不要填写真实订阅。";
      return;
    }
  }
  const priorities = f.priorities
    .split("\n")
    .map((x) => x.trim())
    .filter(Boolean);
  if (priorities.length > 8 || priorities.some((x) => x.length > 100)) {
    formError.value = "最多 8 组优先规则，每组最多 100 字。";
    return;
  }
  if (
    !Number.isInteger(f.hours) ||
    f.hours < 1 ||
    f.hours > 168 ||
    !Number.isInteger(f.minutes) ||
    f.minutes < 1 ||
    f.minutes > 60
  ) {
    formError.value = "请使用 1–168 小时、1–60 分钟的整数间隔。";
    return;
  }
  if (props.scenario === "save-fail") {
    formError.value = "设置保存失败，现有订阅和运行配置未改变。";
    return;
  }
  Object.assign(props.state, {
    subscription_label: label,
    subscription_configured:
      props.state.subscription_configured || !!f.url.trim(),
    update_hours: f.hours,
    check_minutes: f.minutes,
    priorities,
    enabled: f.enabled,
    source: "admin",
  });
  form.value.url = "";
  configDialog.value = false;
  ElMessage.success("设置已保存；订阅地址不回显，节点需更新后导入");
}
function choose(nodes, mode, name) {
  let tiers =
    mode === "manual"
      ? [nodes.filter((n) => n.name === name)]
      : props.state.priorities.length
        ? props.state.priorities.map((rule) =>
            nodes.filter((n) =>
              rule
                .split(/\s+/)
                .every((w) => n.name.toLowerCase().includes(w.toLowerCase())),
            ),
          )
        : [nodes];
  for (const tier of tiers) {
    const n = tier
      .filter((n) => n.delay !== null && n.callback_ok)
      .sort((a, b) => a.delay - b.delay)[0];
    if (n) return n;
  }
  return null;
}
function stageNode(n) {
  selectedMode.value = "manual";
  selectedNode.value = n.name;
  operationMessage.value = "选择尚未应用；原出口未改变。";
}
async function action(kind) {
  if (locked.value) return;
  const gen = generation.value;
  operationMessage.value = "";
  if (kind === "update" && !props.state.subscription_configured) {
    props.state.last_error = "proxy_subscription_required";
    operationMessage.value = "请先保存示例订阅地址。";
    return;
  }
  if (
    kind === "select" &&
    selectedMode.value === "manual" &&
    !selectedNode.value
  ) {
    operationMessage.value = "请选择要固定的节点。";
    return;
  }
  busy.value = true;
  await new Promise((r) => setTimeout(r, 300));
  if (gen !== generation.value) return;
  busy.value = false;
  const s = props.state,
    sc = props.scenario;
  if (sc === "save-fail") {
    operationMessage.value = "保存失败，节点选择和模式未改变。";
    return;
  }
  if (sc === "proxy-update-fail" && kind === "update") {
    s.last_error = "proxy_update_fail";
    operationMessage.value = errors[s.last_error];
    return;
  }
  if (sc === "proxy-controller-fail" || sc === "proxy-rollback-fail") {
    s.last_error =
      sc === "proxy-controller-fail"
        ? "proxy_controller_unavailable"
        : "proxy_rollback_failed";
    s.current_unknown = true;
    s.health = "未确认";
    operationMessage.value = errors[s.last_error];
    selectedMode.value = s.mode;
    selectedNode.value = s.manual_node || "";
    return;
  }
  if (sc === "timeout") {
    s.last_error = "proxy_operation_failed";
    s.health = "检测结果未知";
    operationMessage.value = "检测超时，选择没有改变；不能据此判断回调可达。";
    return;
  }
  const nodes = s.nodes.map((n) => ({ ...n }));
  if (kind === "update" && !nodes.some((n) => n.name === "新加坡 Pro B"))
    nodes.push({
      name: "新加坡 Pro B",
      type: "trojan",
      delay: 102,
      callback_ok: true,
      udp: true,
    });
  if (sc === "proxy-preferred-fail")
    nodes.forEach((n) => {
      if (n.name.startsWith("日本")) n.callback_ok = false;
    });
  if (sc === "proxy-all-fail" || sc === "test-fail")
    nodes.forEach((n) => {
      n.callback_ok = false;
      n.delay = null;
    });
  const mode = kind === "select" ? selectedMode.value : s.mode,
    name = kind === "select" ? selectedNode.value : s.manual_node;
  const chosen = choose(nodes, mode, name);
  if (!chosen) {
    s.last_error = "proxy_no_available_node";
    s.health = "最近检测失败";
    s.last_check = "2026-10-14 09:45";
    if (kind === "check") s.nodes = nodes;
    operationMessage.value = errors[s.last_error];
    selectedMode.value = s.mode;
    selectedNode.value = s.manual_node || "";
    return;
  }
  Object.assign(s, {
    nodes,
    current_node: chosen.name,
    mode,
    manual_node: mode === "manual" ? name : null,
    last_error: "",
    current_unknown: false,
    health: "完整回调检测通过（示例）",
    last_check: "2026-10-14 09:45",
  });
  if (kind === "update") {
    s.last_update = "2026-10-14 09:45";
    s.next_update = s.enabled ? "按保存间隔自动更新" : "已暂停";
    s.usage = { upload: 1.2, download: 18.4, total: 120, expire: "2026-11-01" };
  }
  selectedMode.value = s.mode;
  selectedNode.value = s.manual_node || "";
  operationMessage.value =
    kind === "select"
      ? "节点选择已应用，并完成模拟回调检测。"
      : kind === "update"
        ? "订阅已更新，节点与回调检测结果已同步。"
        : "连接检测完成；自动模式按优先组选择可用出口。";
  ElMessage.success(operationMessage.value);
}
const usagePercent = computed(() =>
  props.state.usage
    ? Math.min(
        100,
        Math.round(
          ((props.state.usage.upload + props.state.usage.download) /
            props.state.usage.total) *
            100,
        ),
      )
    : 0,
);
</script>
<template>
  <div class="proxy-page">
    <div v-if="scenario === 'read-fail'" class="state-panel error-state">
      <el-icon><Warning /></el-icon>
      <h2>代理状态读取失败</h2>
      <p>没有取得当前状态，不能显示为无节点或代理正常。</p>
    </div>
    <template v-else>
      <div class="proxy-scope">
        <el-icon><Connection /></el-icon
        ><span>代理用于已授权的宿主事件回调；微信、飞书收发沿用直连。</span>
      </div>
      <div v-if="!state.available" class="panel state-panel">
        <h2>代理管理尚未配置</h2>
        <p>先由管理员准备服务器上的 Mihomo 控制与私有配置，再导入节点订阅。</p>
        <el-button @click="helpDialog = true">查看配置与恢复步骤</el-button>
      </div>
      <template v-else
        ><el-alert
          v-if="state.last_error"
          :title="errors[state.last_error] || operationMessage"
          :type="state.current_unknown ? 'error' : 'warning'"
          :closable="false"
          show-icon
        />
        <div class="proxy-grid">
          <section class="panel">
            <div class="section-title">
              <div>
                <h2>当前出口</h2>
                <span
                  >{{
                    state.mode === "manual"
                      ? "手动固定节点"
                      : "按优先规则自动选择"
                  }}
                  ·
                  {{ state.enabled ? "自动管理开启" : "自动管理已暂停" }}</span
                >
              </div>
              <el-button
                :loading="busy"
                :disabled="locked"
                :icon="Refresh"
                @click="action('check')"
                >检测连接</el-button
              >
            </div>
            <div class="proxy-current">
              <span class="action-icon blue"
                ><el-icon><Connection /></el-icon
              ></span>
              <div>
                <strong>{{
                  state.current_unknown
                    ? "当前实际节点未确认"
                    : state.current_node || "尚未选择节点"
                }}</strong>
                <p>{{ state.health }}</p>
              </div>
              <el-tag
                v-if="state.current_node && !state.current_unknown"
                type="info"
                effect="plain"
                >{{
                  state.nodes.find((n) => n.name === state.current_node)
                    ?.delay ?? "—"
                }}
                ms</el-tag
              >
            </div>
            <div class="proxy-control">
              <el-radio-group v-model="selectedMode" :disabled="locked"
                ><el-radio-button value="auto">自动选择</el-radio-button
                ><el-radio-button value="manual"
                  >固定节点</el-radio-button
                ></el-radio-group
              ><el-select
                v-if="selectedMode === 'manual'"
                v-model="selectedNode"
                filterable
                placeholder="选择固定节点"
                aria-label="选择固定节点"
                :disabled="locked"
                ><el-option
                  v-for="n in state.nodes"
                  :key="n.name"
                  :label="n.name"
                  :value="n.name" /></el-select
              ><el-button
                type="primary"
                :loading="busy"
                :disabled="locked || !state.nodes.length"
                @click="action('select')"
                >应用选择</el-button
              >
            </div>
            <p class="help">
              {{
                changed
                  ? "当前选择尚未应用；原出口保持不变。"
                  : "优先组：" +
                    (state.priorities.join(" → ") || "全部可用节点")
              }}<br />最近完整检测：{{
                state.last_check
              }}。延迟探测不等于回调可达，应用选择后会检查完整链路。
            </p>
            <el-button
              v-if="state.current_unknown"
              type="danger"
              plain
              @click="helpDialog = true"
              >查看恢复步骤</el-button
            >
          </section>
          <section class="panel proxy-subscription">
            <div class="section-title">
              <div>
                <h2>代理订阅</h2>
                <span
                  >{{ state.subscription_label }} ·
                  {{
                    state.source === "admin" ? "管理页配置" : ".env 初始配置"
                  }}</span
                >
              </div>
              <el-button :icon="Setting" @click="openConfig" :disabled="locked"
                >订阅设置</el-button
              >
            </div>
            <div v-if="state.usage" class="subscription-usage">
              <strong
                >{{ (state.usage.upload + state.usage.download).toFixed(1)
                }}<small> / {{ state.usage.total }} GiB</small></strong
              ><el-progress :percentage="usagePercent" :stroke-width="5" />
              <p>到期：{{ state.usage.expire }}</p>
            </div>
            <p v-else class="muted">订阅尚未提供流量或到期信息。</p>
            <dl class="proxy-dates">
              <dt>上次成功更新</dt>
              <dd>{{ state.last_update }}</dd>
              <dt>下次更新</dt>
              <dd>
                {{ state.enabled ? state.next_update : "自动管理已暂停" }}
              </dd>
            </dl>
            <el-button
              :icon="Refresh"
              :loading="busy"
              :disabled="locked"
              @click="action('update')"
              >立即更新订阅</el-button
            >
          </section>
        </div>
        <section class="panel proxy-nodes">
          <div class="section-title">
            <div>
              <h2>
                订阅节点 <span>{{ state.nodes.length }} 个</span>
              </h2>
              <span>节点来自订阅。先选候选节点，再应用到当前出口。</span>
            </div>
            <el-input
              v-model="nodeSearch"
              clearable
              placeholder="搜索节点名称"
              aria-label="搜索节点名称"
              class="compact-search"
            />
          </div>
          <el-table v-if="rows.length" :data="rows"
            ><el-table-column label="节点" min-width="200"
              ><template #default="{ row }"
                ><strong>{{ row.name }}</strong
                ><el-tag
                  v-if="
                    !state.current_unknown && row.name === state.current_node
                  "
                  size="small"
                  type="success"
                  class="node-current-tag"
                  >当前出口</el-tag
                ></template
              ></el-table-column
            ><el-table-column
              prop="type"
              label="协议"
              width="100"
            /><el-table-column label="延迟探测" width="145"
              ><template #default="{ row }">{{
                row.delay !== null ? row.delay + " ms" : "未通过 / 未取得结果"
              }}</template></el-table-column
            ><el-table-column label="UDP" width="80"
              ><template #default="{ row }">{{
                row.udp ? "支持" : "—"
              }}</template></el-table-column
            ><el-table-column label="" width="145"
              ><template #default="{ row }"
                ><el-button
                  link
                  type="primary"
                  :disabled="locked"
                  @click="stageNode(row)"
                  >固定此节点</el-button
                ></template
              ></el-table-column
            ></el-table
          >
          <div v-else class="inline-empty">
            <h3>
              {{ state.nodes.length ? "没有匹配的节点" : "还没有订阅节点" }}
            </h3>
            <p>
              {{
                state.nodes.length
                  ? "调整搜索条件。"
                  : "保存示例订阅后，点击立即更新订阅导入节点。"
              }}
            </p>
            <el-button v-if="state.nodes.length" @click="nodeSearch = ''"
              >清除节点搜索</el-button
            ><el-button
              v-else
              type="primary"
              :disabled="locked"
              @click="openConfig"
              >配置订阅</el-button
            >
          </div>
        </section>
        <p v-if="operationMessage" class="proxy-result">
          {{ operationMessage }}
        </p></template
      ></template
    >
    <el-dialog
      v-model="configDialog"
      title="订阅与自动管理设置"
      width="660px"
      :close-on-click-modal="false"
      class="flow-dialog"
      ><div class="flow-body">
        <el-form label-position="top"
          ><el-form-item label="订阅地址"
            ><el-input
              v-model="form.url"
              type="password"
              show-password
              placeholder="留空保留原地址；仅填写 HTTPS 示例订阅"
              aria-label="代理订阅地址"
            />
            <p class="help">
              不回显订阅秘密，仅接受 Clash / Mihomo YAML
              节点订阅。原型示例：https://subscription.example.test/nodes
            </p></el-form-item
          >
          <div class="form-grid">
            <el-form-item label="订阅更新间隔（小时）"
              ><el-input-number
                v-model="form.hours"
                :min="1"
                :max="168"
                aria-label="订阅更新间隔" /></el-form-item
            ><el-form-item label="连接检测间隔（分钟）"
              ><el-input-number
                v-model="form.minutes"
                :min="1"
                :max="60"
                aria-label="连接检测间隔"
            /></el-form-item>
          </div>
          <el-form-item label="自动选择的节点优先规则"
            ><el-input
              v-model="form.priorities"
              type="textarea"
              :rows="3"
              placeholder="日本 Pro&#10;新加坡 Pro&#10;美国 Pro"
              aria-label="节点优先规则"
            />
            <p class="help">
              每行一个优先组，同组关键词全部匹配；按组依次尝试。留空选择全部可用节点。
            </p></el-form-item
          ><el-form-item
            ><el-switch
              v-model="form.enabled"
              active-text="自动更新订阅与检测连接"
              aria-label="自动管理代理"
          /></el-form-item>
          <p class="help">
            关闭自动管理只暂停定时更新和检测，不停止代理进程或当前出口。
          </p></el-form
        ><el-alert
          v-if="formError"
          :title="formError"
          type="error"
          :closable="false"
        />
      </div>
      <template #footer
        ><el-button @click="configDialog = false">取消</el-button
        ><el-button type="primary" @click="saveConfig"
          >保存订阅设置</el-button
        ></template
      ></el-dialog
    >
    <el-dialog v-model="helpDialog" title="代理配置与恢复步骤" width="660px"
      ><div class="guide-text">
        <p>
          首次配置：由管理员在服务器提供 Mihomo
          控制接口和独立私有配置，限制访问范围。这里管理订阅与节点，不安装服务器代理进程。
        </p>
        <p>
          订阅更新或选节点失败：保留或恢复上次配置，核对原节点与完整回调检测结果。不要把延迟探测成功当回调成功。
        </p>
        <p>
          回退失败或控制接口不可用：停止继续切换，先确认代理进程与实际出口；状态未确认时不显示为健康，不擅自改为直连。
        </p>
        <p>
          本轮只有模拟操作；服务器配置、重启、私有订阅或真实检测需另行实施。
        </p>
      </div>
      <template #footer
        ><el-button type="primary" @click="helpDialog = false"
          >关闭</el-button
        ></template
      ></el-dialog
    >
  </div>
</template>
