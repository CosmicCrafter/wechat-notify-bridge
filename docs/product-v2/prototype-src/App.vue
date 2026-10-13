<script setup>
import { ref, reactive, computed, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  Odometer,
  ChatLineRound,
  Grid,
  Connection,
  Setting,
  ArrowRight,
  Plus,
  Search,
  Refresh,
  Download,
  CopyDocument,
  CircleCheck,
  Warning,
  Clock,
  Document,
  Monitor,
  Key,
  Switch,
  Link,
} from "@element-plus/icons-vue";
import { seed, labels, sampleSecrets } from "./mock.js";
const nav = [
  ["overview", "总览", Odometer],
  ["messages", "消息", ChatLineRound],
  ["apps", "接入应用", Grid],
  ["connections", "通信连接", Connection],
  ["settings", "设置与帮助", Setting],
];
const page = ref("overview"),
  scenario = ref("normal"),
  review = ref(false),
  store = reactive(seed()),
  search = ref(""),
  appFilter = ref(""),
  botFilter = ref(""),
  statusFilter = ref(""),
  messageTab = ref("deliveries");
const drawer = ref(false),
  selected = ref(null),
  appDialog = ref(false),
  appStep = ref(0),
  appEdit = ref(null),
  configDialog = ref(false),
  configured = ref(null),
  configTarget = ref("codex"),
  transport = ref("remote"),
  busy = ref(false),
  error = ref(""),
  exportError = ref(""),
  guide = ref(null),
  guideDialog = ref(false);
const appForm = reactive({
  name: "",
  target: "codex",
  bot_ids: [],
  default_bot_id: "",
});
const connDialog = ref(false),
  connStep = ref(0),
  connEdit = ref(null),
  returnToApp = ref(false),
  connError = ref(""),
  testStatus = ref("idle"),
  testReceipt = ref(null),
  confirmed = ref(false),
  callbackReady = ref(false),
  wechatBound = ref(false),
  qrExpired = ref(false);
const connForm = reactive({
  name: "",
  platform: "feishu",
  app_id: "",
  app_secret: "",
  owner_id: "",
  verification_token: "",
  encrypt_key: "",
});
const titles = {
  overview: ["今天的中转站", "连接程序与消息平台，让每一次通知都有迹可循。"],
  messages: ["消息", "从应用、连接或去重键，找到通知与回复。"],
  apps: ["接入应用", "为每个 AI 宿主或业务程序分配独立身份和通信权限。"],
  connections: ["通信连接", "管理微信、飞书的具体连接与收发状态。"],
  settings: ["设置与帮助", "部署维护、客户端接入和服务设置的统一入口。"],
};
const targetNames = { codex: "Codex", claude: "Claude Code", http: "业务系统" };
function go(id) {
  page.value = id;
  search.value = "";
  appFilter.value = "";
  botFilter.value = "";
  statusFilter.value = "";
  error.value = "";
}
function nameOfApp(id) {
  return store.apps.find((x) => x.id === id)?.name || "连接测试";
}
function nameOfBot(id) {
  return store.connections.find((x) => x.id === id)?.name || id;
}
function typeOf(id) {
  return store.connections.find((x) => x.id === id)?.platform === "wechat"
    ? "微信"
    : "飞书";
}
function resetScene() {
  Object.assign(store, seed(scenario.value === "empty"));
  appDialog.value = false;
  connDialog.value = false;
  configDialog.value = false;
  drawer.value = false;
  search.value = "";
  appFilter.value = "";
  botFilter.value = "";
  statusFilter.value = "";
  returnToApp.value = false;
  error.value = "";
  exportError.value = "";
}
watch(scenario, resetScene);
watch(
  () => appForm.bot_ids,
  (ids) => {
    if (!ids.includes(appForm.default_bot_id)) appForm.default_bot_id = "";
  },
  { deep: true },
);
watch(configTarget, (v) => {
  if (v === "http") transport.value = "http";
  else if (transport.value === "http") transport.value = "remote";
});
const hasReadError = computed(() => scenario.value === "read-fail");
const available = computed(() =>
  store.connections.filter((x) => x.enabled && x.state === "ready"),
);
const grantChoices = computed(() =>
  appEdit.value ? store.connections : available.value,
);
const readyCount = computed(() => available.value.length);
const failedCount = computed(
  () => store.messages.filter((x) => x.status === "failed").length,
);
const unknownCount = computed(
  () => store.messages.filter((x) => x.status === "unknown").length,
);
const filtered = computed(() =>
  store.messages.filter(
    (m) =>
      (!appFilter.value || m.app === appFilter.value) &&
      (!botFilter.value || m.bot === botFilter.value) &&
      (!statusFilter.value || m.status === statusFilter.value) &&
      (!search.value ||
        [m.title, m.id, m.key, m.cid, nameOfApp(m.app), nameOfBot(m.bot)].some(
          (s) => s.toLowerCase().includes(search.value.toLowerCase()),
        )),
  ),
);
const replies = computed(() =>
  filtered.value.flatMap((m) =>
    m.replies.map((r, i) => ({ ...r, id: m.id + "-" + i, message: m })),
  ),
);
const filteredApps = computed(() =>
  store.apps.filter(
    (a) =>
      !search.value ||
      a.name.toLowerCase().includes(search.value.toLowerCase()),
  ),
);
const filteredConnections = computed(() =>
  store.connections.filter(
    (a) =>
      (!botFilter.value || a.platform === botFilter.value) &&
      (!search.value ||
        a.name.toLowerCase().includes(search.value.toLowerCase())),
  ),
);
function inspect(m) {
  selected.value = m;
  drawer.value = true;
}
function failedView(kind = "failed") {
  go("messages");
  statusFilter.value = kind;
}
function clearFilters() {
  search.value = "";
  appFilter.value = "";
  botFilter.value = "";
  statusFilter.value = "";
}
function openApp(row = null) {
  appEdit.value = row;
  Object.assign(
    appForm,
    row
      ? {
          name: row.name,
          target: row.target,
          bot_ids: [...row.bot_ids],
          default_bot_id: row.default_bot_id || "",
        }
      : { name: "", target: "codex", bot_ids: [], default_bot_id: "" },
  );
  appStep.value = 0;
  error.value = "";
  appDialog.value = true;
}
function appNext() {
  error.value = "";
  if (appStep.value === 0) {
    if (!/^[a-zA-Z0-9_\-\u4e00-\u9fff]{1,32}$/.test(appForm.name.trim())) {
      error.value =
        "填写 1–32 字的应用名称，使用中文、字母、数字、下划线或短横线。";
      return;
    }
    if (
      [
        "admin",
        "heartbeat",
        "command",
        "system",
        "系统",
        "微信通知桥",
      ].includes(appForm.name.trim().toLowerCase())
    ) {
      error.value = "此名称由系统保留，请使用应用自己的名称。";
      return;
    }
    if (
      store.apps.some(
        (a) =>
          a.name.toLowerCase() === appForm.name.trim().toLowerCase() &&
          a !== appEdit.value,
      )
    ) {
      error.value = "已有同名应用，请换一个名称。";
      return;
    }
    appStep.value = 1;
  } else {
    if (!appForm.bot_ids.length && !appEdit.value) {
      error.value = "至少选择一个可用通信连接后继续。";
      return;
    }
    appStep.value = 2;
  }
}
const delay = () => new Promise((r) => setTimeout(r, 360));
async function saveApp() {
  error.value = "";
  busy.value = true;
  await delay();
  busy.value = false;
  if (scenario.value === "save-fail") {
    error.value = "保存失败，本次应用未创建。信息已保留，可修改后重试。";
    return;
  }
  let row = appEdit.value;
  if (row) {
    Object.assign(row, {
      name: appForm.name.trim(),
      bot_ids: [...appForm.bot_ids],
      default_bot_id: appForm.default_bot_id || null,
    });
    ElMessage.success("应用权限已更新");
  } else {
    row = {
      id: "app_demo_" + (store.apps.length + 1),
      name: appForm.name.trim(),
      target: appForm.target,
      enabled: true,
      bot_ids: [...appForm.bot_ids],
      default_bot_id: appForm.default_bot_id || null,
      last: "尚未调用",
      hasNewKey: true,
    };
    store.apps.push(row);
  }
  appDialog.value = false;
  go("apps");
  if (!appEdit.value) openConfig(row);
}
function openConfig(row) {
  configured.value = row;
  configTarget.value = row.target || "codex";
  transport.value = row.target === "http" ? "http" : "remote";
  exportError.value = "";
  configDialog.value = true;
}
const configText = computed(() => {
  if (!configured.value) return "";
  const a = configured.value;
  const connection = {
    demo: true,
    base_url: "https://notify.example.test/bridge",
    application_id: a.id,
    application_name: a.name,
    default_bot_id: a.default_bot_id || null,
  };
  if (transport.value === "remote")
    return JSON.stringify(
      {
        ...connection,
        mcp_url: "https://notify.example.test/bridge/mcp",
        authentication: "OAuth（在宿主中授权）",
      },
      null,
      2,
    );
  if (transport.value === "stdio")
    return JSON.stringify(
      {
        ...connection,
        transport: "stdio",
        credential_file: "<仅本人可读的私有配置路径>",
        python: "<Python 3.12+ 解释器路径>",
        server: "<http_bridge.py 路径>",
        api_key: a.hasNewKey ? "DEMO_KEY_NOT_VALID" : "CONFIGURE_SEPARATELY",
      },
      null,
      2,
    );
  return JSON.stringify(
    {
      ...connection,
      transport: "HTTP",
      api_key: a.hasNewKey ? "DEMO_KEY_NOT_VALID" : "CONFIGURE_SEPARATELY",
      headers: { Authorization: "Bearer <私有 API Key>" },
      message_endpoint: "/api/messages",
      receipt_endpoint: "/api/deliveries",
    },
    null,
    2,
  );
});
async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    ElMessage.success("已复制演示内容");
  } catch {
    ElMessage.info("浏览器未允许剪贴板，请在配置文本中手动选择复制。");
  }
}
function download(content, name, type = "text/plain") {
  const u = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement("a");
  a.href = u;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(u), 1000);
}
function exportConfig() {
  if (scenario.value === "save-fail") {
    exportError.value =
      "资料生成失败，应用及原有权限未改变；可继续查看并手动复制配置。";
    return;
  }
  exportError.value = "";
  download(
    configText.value,
    "notify-bridge-demo-" + configTarget.value + ".json",
    "application/json",
  );
  ElMessage.success("已下载演示配置，仅含占位数据");
}
const instructions = computed(
  () =>
    `# ${targetNames[configTarget.value]} 接入 Notify Bridge（演示）\n\n这是原型占位资料，不能直接连接服务。\n\n1. 服务地址、应用身份及默认连接：见演示配置 JSON。\n2. ${transport.value === "remote" ? "在支持 Streamable HTTP 与 OAuth 的宿主中添加 MCP 地址，并在宿主授权；JSON 文件不等于已授权。" : transport.value === "stdio" ? "使用独立 Python 3.12+ 环境及现有 MCP 适配；API Key 保存在私有文件，不写入规则或提示词。" : "在程序后端的环境变量或私有配置中保存 API Key，调用统一 HTTP API。"}\n3. ${configTarget.value === "claude" ? "Claude Code 先导出通用 MCP 配置与使用说明，具体安装格式和命令需在实施时定向验证。" : "以目标宿主支持的配置方式导入，不把一种插件 ZIP 当作所有宿主的安装器。"}\n4. 登记会话，选择已授权连接；一次事件使用固定 dedup_key。\n5. 发出一次经本人授权的测试消息，查询原回执并由手机收件/回复验收。\n6. 失败或未知先查原结果，禁止换去重键自动补发。\n\nCodex/Claude 是外部调用方；Notify Bridge 内部不运行 AI Agent。\n`,
);
function beginConnectionFromApp() {
  returnToApp.value = true;
  appDialog.value = false;
  openConnection();
}
function openConnection(row = null) {
  connEdit.value = row;
  Object.assign(connForm, {
    name: row?.name || "",
    platform: row?.platform || "feishu",
    app_id: row?.app_id || "",
    app_secret: "",
    owner_id: row?.owner_id || "",
    verification_token: "",
    encrypt_key: "",
  });
  connStep.value = row ? 1 : 0;
  connError.value = "";
  testStatus.value = "idle";
  testReceipt.value = null;
  confirmed.value = false;
  callbackReady.value = !!row && row.state === "ready";
  wechatBound.value =
    !!row && row.platform === "wechat" && row.state === "ready";
  qrExpired.value = false;
  connDialog.value = true;
}
function fillSample() {
  Object.assign(connForm, sampleSecrets);
}
async function connectionNext() {
  connError.value = "";
  if (connStep.value === 0) {
    if (!connForm.name.trim()) {
      connError.value = "请填写通信连接名称。";
      return;
    }
    if (
      store.connections.some(
        (x) => x.name === connForm.name.trim() && x !== connEdit.value,
      )
    ) {
      connError.value = "已有同名连接，请使用另一个名称。";
      return;
    }
    if (scenario.value === "save-fail") {
      connError.value = "创建失败，输入已保留，未新增连接。";
      return;
    }
    if (!connEdit.value) {
      const draft = {
        id: "conn_demo_" + (store.connections.length + 1),
        name: connForm.name.trim(),
        platform: connForm.platform,
        enabled: true,
        state: "pending",
        owner: "未配置",
        last: "—",
        test: "尚未测试",
        app_id: "",
        owner_id: "",
      };
      store.connections.push(draft);
      connEdit.value = store.connections[store.connections.length - 1];
    }
    connStep.value = 1;
    return;
  }
  if (connForm.platform === "feishu") {
    if (
      store.connections.some(
        (c) =>
          c !== connEdit.value &&
          c.platform === "feishu" &&
          c.state === "ready" &&
          c.app_id === connForm.app_id.trim(),
      )
    ) {
      connError.value = "此飞书应用已经绑定，请管理原连接，不要重复创建。";
      return;
    }
    if (
      !connForm.app_id.trim() ||
      !connForm.owner_id.trim() ||
      ((!connEdit.value ||
        (connEdit.value.state === "pending" && !connEdit.value.configured)) &&
        ["app_secret", "verification_token", "encrypt_key"].some(
          (k) => !connForm[k].trim(),
        ))
    ) {
      connError.value = "请补全应用 ID、接收人和三项凭据。这里只能填写示例值。";
      return;
    }
  } else if (!wechatBound.value) {
    connError.value = "请在演示区完成模拟扫码确认。";
    return;
  }
  busy.value = true;
  await delay();
  busy.value = false;
  if (scenario.value === "save-fail") {
    connError.value =
      "连接配置保存失败。信息已保留，不会显示配置完成或修改已有连接。";
    return;
  }
  Object.assign(connEdit.value, {
    name: connForm.name.trim(),
    app_id: connForm.app_id,
    owner_id: connForm.owner_id,
    configured: true,
    owner:
      connForm.platform === "wechat" ? "本人 · 微信账号" : "本人 · 飞书账号",
  });
  const lastTest = store.messages.find(
    (m) => m.bot === connEdit.value.id && m.app === "test",
  );
  testStatus.value = lastTest?.status === "unknown" ? "unknown" : "idle";
  testReceipt.value = testStatus.value === "unknown" ? lastTest : null;
  confirmed.value = false;
  connStep.value = 2;
}
const callbackURL = computed(
  () =>
    `https://notify.example.test/bridge/channels/feishu/${connEdit.value?.id || "conn_demo_new"}/callback`,
);
async function testConnection() {
  connError.value = "";
  confirmed.value = false;
  testStatus.value = "testing";
  await delay();
  const result =
    scenario.value === "timeout"
      ? "unknown"
      : scenario.value === "test-fail"
        ? "failed"
        : "accepted";
  testStatus.value = result;
  testReceipt.value = {
    id: "test_demo_" + Date.now(),
    title: "通信连接测试",
    app: "test",
    bot: connEdit.value?.id || "conn_demo_new",
    at: "2026-10-14 09:45",
    status: result,
    code:
      result === "unknown"
        ? "network_timeout"
        : result === "failed"
          ? connForm.platform === "wechat"
            ? "wechat_prepare_failed"
            : "feishu_rejected"
          : "no_error_reported",
    key: "connection-test-demo-" + (store.messages.length + 1),
    cid: "conversation_test",
    detail:
      result === "unknown"
        ? "请求超时，平台是否接受尚未确认。"
        : result === "failed"
          ? "平台拒绝测试请求。请核对配置或微信上下文；本次测试没有成功。"
          : "平台接口未报告错误。仍需在手机确认实际收件和回复。",
    next:
      result === "unknown"
        ? "查询原测试回执，勿切换连接或自动重发。"
        : result === "failed"
          ? "检查对应平台配置，再由管理员明确发起新的测试。"
          : "打开对应平台，在手机确认收到，再回复一条测试文字。",
    replies: [],
  };
  store.messages.unshift(testReceipt.value);
  testReceipt.value = store.messages[0];
  connEdit.value.test =
    result === "accepted"
      ? "平台已接受 · 待确认"
      : result === "failed"
        ? "测试失败"
        : "测试结果未知";
}
function confirmReceipt() {
  confirmed.value = true;
  if (testReceipt.value)
    testReceipt.value.replies = [
      {
        at: "09:46",
        source: connForm.platform === "wechat" ? "微信" : "飞书",
        text: "测试收到。",
      },
    ];
}
function finishConnection() {
  let row = connEdit.value;
  const values = {
    name: connForm.name.trim(),
    platform: connForm.platform,
    enabled: row ? row.enabled : true,
    state: "ready",
    owner:
      connForm.platform === "wechat" ? "本人 · 微信账号" : "本人 · 飞书账号",
    last: confirmed.value ? "09:46" : "—",
    test: confirmed.value
      ? "人工已确认收件/回复（示例）"
      : testStatus.value === "accepted"
        ? "平台已接受 · 待确认"
        : testStatus.value === "failed"
          ? "测试失败"
          : testStatus.value === "unknown"
            ? "测试结果未知"
            : "尚未测试",
    app_id: connForm.app_id,
    owner_id: connForm.owner_id,
  };
  if (!row) {
    row = { id: "conn_demo_" + (store.connections.length + 1), ...values };
    store.connections.push(row);
  } else Object.assign(row, values);
  if (testReceipt.value) testReceipt.value.bot = row.id;
  connDialog.value = false;
  go("connections");
  ElMessage.success("连接已保存，测试结果单独记录");
  if (returnToApp.value) {
    returnToApp.value = false;
    appDialog.value = true;
    appStep.value = 1;
    error.value = "";
  }
}
async function toggleConnection(row) {
  try {
    await ElMessageBox.confirm(
      row.enabled
        ? "停用后阻止新调用并暂停后台收发，历史记录保留。"
        : "启用后恢复该连接的后续调用权限。",
      row.enabled ? "停用通信连接" : "启用通信连接",
      { confirmButtonText: "确认", cancelButtonText: "取消", type: "warning" },
    );
    if (scenario.value === "save-fail") {
      ElMessage.error("保存失败，状态未改变");
      return;
    }
    row.enabled = !row.enabled;
    ElMessage.success("连接状态已更新");
  } catch {}
}
function openGuide(kind) {
  guide.value = kind;
  guideDialog.value = true;
}
const guideText = computed(
  () =>
    ({
      deploy:
        "部署维护中转站\n\n1. 提供服务主机、HTTPS 地址、访问方式与数据目录。\n2. 由站外 Codex 或管理员依据仓库 README 和维护手册部署，生产写入前单独授权。\n3. 首次实例初始化新密钥；接管实例使用配套原数据库与密钥。\n4. 单进程、单 worker；开发与生产目录/凭据/目标隔离。\n5. 升级前做 SQLite 一致备份，保存镜像，隔离验证恢复。\n6. Codex 不进入服务运行链路。",
      ai: "AI 接入中转站\n\n从“接入应用”新增 Codex 或 Claude Code 身份，选择授权连接与默认连接，再获得远程 MCP / 本机 stdio 配置及规则。\n\n远程 MCP 需宿主支持 OAuth 并由本人授权。已有身份只存 Key 哈希；导出不得偷偷重置旧 Key。\n\nClaude Code 暂沿用通用 MCP 资料，专用安装说明在实施时验证。规则文件本身没有通信能力。",
      http: "业务系统接入通知\n\n创建业务系统身份，选择通信权限，导出 HTTP 配置和说明。API Key 保存在后端环境变量或私有文件。\n\n登记会话 → 固定 bot_id 和 dedup_key → /api/messages → /api/deliveries → 按游标读取回复。\n\n同一事件复用原去重键；失败或结果未知先查原记录，禁止自动切换连接。",
      proxy:
        "回调代理\n\n复用现有代理页的订阅、节点、检测与回退能力，归入“设置与帮助 → 服务设置”。\n\n只控制允许的 AI 宿主事件回调出站，不代表微信/飞书整体走代理。本轮展示归位，未接入真实节点编辑。",
      session:
        "手机会话登录\n\n原“会话登录”页面归入“设置与帮助 → 手机会话登录”。\n\n这是本人手机页的认证入口，不是接入应用或通信连接。历史、回复、任务答复仍由原手机页承载，本轮未重做手机界面。",
    })[guide.value] || "",
);
</script>
<template>
  <el-config-provider
    ><div class="shell">
      <aside class="sidebar">
        <div class="brand">
          <div class="brand-mark">↗</div>
          <div><strong>Notify Bridge</strong><small>统一消息中转站</small></div>
        </div>
        <p class="side-caption">管理工作空间</p>
        <nav>
          <button
            v-for="[id, label, icon] in nav"
            :key="id"
            :class="['nav-item', { active: page === id }]"
            @click="go(id)"
          >
            <el-icon><component :is="icon" /></el-icon>{{ label
            }}<span v-if="id === 'messages' && failedCount" class="nav-count">{{
              failedCount
            }}</span>
          </button>
        </nav>
        <div class="sidebar-bottom">
          <span class="mini-status"><i />本地交互原型</span>
          <p>v0.1 · 产品设计候选</p>
          <small>Codex 等 AI 在服务外部接入。</small>
        </div>
      </aside>
      <div class="main-shell">
        <header class="topbar">
          <div class="crumb">
            管理中心 <el-icon><ArrowRight /></el-icon
            ><span>{{ nav.find((n) => n[0] === page)[1] }}</span>
          </div>
          <div class="top-actions">
            <span class="demo-pill">模拟数据 · 不连接服务</span
            ><el-button text :icon="Switch" @click="review = !review"
              >评审场景</el-button
            ><span class="avatar">管</span>
          </div>
        </header>
        <div v-if="review" class="review-bar">
          <span>评审工具</span
          ><el-select
            v-model="scenario"
            aria-label="评审场景"
            class="scene-select"
            ><el-option label="正常数据" value="normal" /><el-option
              label="首次使用 · 无数据"
              value="empty" /><el-option
              label="列表读取失败"
              value="read-fail" /><el-option
              label="保存 / 导出失败"
              value="save-fail" /><el-option
              label="连接测试失败"
              value="test-fail" /><el-option
              label="连接测试超时"
              value="timeout" /></el-select
          ><el-button :icon="Refresh" @click="resetScene">重置演示</el-button
          ><small>切换会恢复样例。刷新也会重置；仅可填写示例值。</small>
        </div>
        <main class="content">
          <div class="heading">
            <div>
              <div class="eyebrow">
                {{
                  page === "overview" ? "WORKSPACE OVERVIEW" : "NOTIFY BRIDGE"
                }}
              </div>
              <h1>{{ titles[page][0] }}</h1>
              <p>{{ titles[page][1] }}</p>
            </div>
            <el-button
              v-if="page === 'apps'"
              type="primary"
              :icon="Plus"
              @click="openApp()"
              >新增接入应用</el-button
            ><el-button
              v-if="page === 'connections'"
              type="primary"
              :icon="Plus"
              @click="openConnection()"
              >新增通信连接</el-button
            >
          </div>
          <div
            v-if="hasReadError && page !== 'settings'"
            class="state-panel error-state"
          >
            <el-icon><Warning /></el-icon>
            <h2>暂时无法读取数据</h2>
            <p>请求未完成，不能把读取失败当成“没有记录”。</p>
            <el-button @click="scenario = 'normal'"
              >重新读取（恢复示例）</el-button
            >
          </div>
          <template v-else-if="page === 'overview'"
            ><div class="stats">
              <button @click="go('apps')">
                <span>接入应用</span
                ><strong>{{ store.apps.length }}<small>个</small></strong>
                <p>
                  独立身份与通信权限<el-icon><ArrowRight /></el-icon>
                </p></button
              ><button @click="go('connections')">
                <span>就绪连接</span
                ><strong
                  >{{ readyCount
                  }}<small>/ {{ store.connections.length }}</small></strong
                >
                <p>
                  绑定与配置完成<el-icon><ArrowRight /></el-icon>
                </p></button
              ><button @click="failedView()">
                <span>待排查失败</span
                ><strong class="red">{{ failedCount }}<small>条</small></strong>
                <p>
                  定位原回执与失败原因<el-icon><ArrowRight /></el-icon>
                </p></button
              ><button @click="failedView('unknown')">
                <span>结果未知</span
                ><strong class="amber"
                  >{{ unknownCount }}<small>条</small></strong
                >
                <p>
                  先核查，不自动重发<el-icon><ArrowRight /></el-icon>
                </p>
              </button>
            </div>
            <div v-if="failedCount" class="attention">
              <div class="attention-icon">
                <el-icon><Warning /></el-icon>
              </div>
              <div>
                <strong>微信连接最近的通知被拒绝</strong>
                <p>接收连接正常不代表发送可达。查看原回执，再决定下一步。</p>
              </div>
              <el-button @click="failedView()"
                >查看失败记录 <el-icon><ArrowRight /></el-icon
              ></el-button>
            </div>
            <div class="overview-grid">
              <section class="panel">
                <div class="section-title">
                  <div>
                    <h2>最近的通知</h2>
                    <span>示例记录 · 2026-10-14</span>
                  </div>
                  <el-button link @click="go('messages')"
                    >查看全部 <el-icon><ArrowRight /></el-icon
                  ></el-button>
                </div>
                <div v-if="!store.messages.length" class="compact-empty">
                  <el-icon><ChatLineRound /></el-icon>
                  <h3>从第一条通知开始</h3>
                  <p>先添加通信连接，再让应用接入。</p>
                  <el-button
                    type="primary"
                    @click="
                      go('connections');
                      openConnection();
                    "
                    >新增通信连接</el-button
                  >
                </div>
                <button
                  v-for="m in store.messages.slice(0, 4)"
                  :key="m.id"
                  class="recent-item"
                  @click="inspect(m)"
                >
                  <div
                    class="platform-icon"
                    :class="typeOf(m.bot) === '微信' ? 'wechat' : 'feishu'"
                  >
                    <el-icon><ChatLineRound /></el-icon>
                  </div>
                  <div>
                    <strong>{{ m.title }}</strong
                    ><small
                      >{{ nameOfApp(m.app) }} · {{ m.at.slice(-5) }}</small
                    >
                  </div>
                  <span :class="['status', m.status]"
                    ><i />{{ labels[m.status] }}</span
                  ><el-icon><ArrowRight /></el-icon>
                </button>
              </section>
              <section class="panel quick-start">
                <div class="section-title"><h2>快速开始</h2></div>
                <button
                  @click="
                    go('apps');
                    openApp();
                  "
                >
                  <span class="action-icon blue"
                    ><el-icon><Grid /></el-icon
                  ></span>
                  <div>
                    <strong>让一个新应用接入</strong>
                    <p>分配权限，获得 MCP / API 配置。</p>
                  </div>
                  <el-icon><ArrowRight /></el-icon></button
                ><button
                  @click="
                    go('connections');
                    openConnection();
                  "
                >
                  <span class="action-icon green"
                    ><el-icon><Connection /></el-icon
                  ></span>
                  <div>
                    <strong>连接一个通信平台</strong>
                    <p>完成配置，测试发送和回复。</p>
                  </div>
                  <el-icon><ArrowRight /></el-icon></button
                ><button @click="openGuide('deploy')">
                  <span class="action-icon neutral"
                    ><el-icon><Monitor /></el-icon
                  ></span>
                  <div>
                    <strong>部署与维护中转站</strong>
                    <p>从仓库资料开始，站外 AI 协助。</p>
                  </div>
                  <el-icon><ArrowRight /></el-icon>
                </button>
              </section>
            </div>
            <section class="panel connection-summary">
              <div class="section-title">
                <h2>通信连接</h2>
                <el-button link @click="go('connections')"
                  >管理连接 <el-icon><ArrowRight /></el-icon
                ></el-button>
              </div>
              <div class="connection-summary-grid">
                <div v-for="c in store.connections" :key="c.id">
                  <span class="platform-icon" :class="c.platform"
                    ><el-icon><ChatLineRound /></el-icon
                  ></span>
                  <div>
                    <strong>{{ c.name }}</strong>
                    <p>{{ c.test }}</p>
                  </div>
                  <span :class="['status', !c.enabled ? 'disabled' : c.state]"
                    ><i />{{ !c.enabled ? "已停用" : labels[c.state] }}</span
                  >
                </div>
                <p v-if="!store.connections.length" class="muted">
                  尚未添加连接。微信与飞书都可从这里开始。
                </p>
              </div>
            </section></template
          >
          <template v-else-if="page === 'messages'"
            ><section class="panel">
              <div class="filterbar">
                <el-input
                  v-model="search"
                  :prefix-icon="Search"
                  clearable
                  aria-label="搜索消息"
                  placeholder="搜索摘要、记录 ID 或去重键"
                /><el-select
                  v-model="appFilter"
                  clearable
                  placeholder="全部应用"
                  aria-label="按接入应用筛选"
                  ><el-option
                    v-for="a in store.apps"
                    :key="a.id"
                    :label="a.name"
                    :value="a.id" /></el-select
                ><el-select
                  v-model="botFilter"
                  clearable
                  placeholder="全部连接"
                  aria-label="按通信连接筛选"
                  ><el-option
                    v-for="c in store.connections"
                    :key="c.id"
                    :label="c.name"
                    :value="c.id" /></el-select
                ><el-select
                  v-model="statusFilter"
                  clearable
                  placeholder="全部投递结果"
                  aria-label="按投递结果筛选"
                  ><el-option label="平台已接受" value="accepted" /><el-option
                    label="投递失败"
                    value="failed" /><el-option
                    label="结果未知"
                    value="unknown" /></el-select
                ><el-button text @click="clearFilters">重置筛选</el-button>
              </div>
              <div class="tabs-row">
                <el-radio-group v-model="messageTab"
                  ><el-radio-button value="deliveries">投递记录</el-radio-button
                  ><el-radio-button value="replies"
                    >回复</el-radio-button
                  ></el-radio-group
                ><span class="muted"
                  >{{
                    messageTab === "deliveries"
                      ? filtered.length
                      : replies.length
                  }}
                  条记录</span
                >
              </div>
              <el-table
                v-if="(messageTab === 'deliveries' ? filtered : replies).length"
                :data="messageTab === 'deliveries' ? filtered : replies"
                @row-click="(row) => inspect(row.message || row)"
                class="clickable-table"
                ><el-table-column
                  :label="messageTab === 'deliveries' ? '通知摘要' : '关联通知'"
                  min-width="220"
                  ><template #default="{ row }"
                    ><div class="table-primary">
                      {{ (row.message || row).title }}
                    </div>
                    <small class="mono muted">{{
                      (row.message || row).id
                    }}</small></template
                  ></el-table-column
                ><el-table-column label="接入应用 / 连接" min-width="230"
                  ><template #default="{ row }"
                    ><span>{{ nameOfApp((row.message || row).app) }}</span
                    ><small class="block muted">{{
                      nameOfBot((row.message || row).bot)
                    }}</small></template
                  ></el-table-column
                ><el-table-column
                  v-if="messageTab === 'deliveries'"
                  label="投递结果"
                  width="150"
                  ><template #default="{ row }"
                    ><span :class="['status', row.status]"
                      ><i />{{ labels[row.status] }}</span
                    ></template
                  ></el-table-column
                ><el-table-column v-else label="回复摘要" min-width="180"
                  ><template #default="{ row }">{{
                    row.text
                  }}</template></el-table-column
                ><el-table-column label="时间" width="120"
                  ><template #default="{ row }"
                    ><span class="muted">{{ row.at.slice(-5) }}</span></template
                  ></el-table-column
                ><el-table-column label="" width="85"
                  ><template #default="{ row }"
                    ><el-button
                      link
                      type="primary"
                      @click.stop="inspect(row.message || row)"
                      >详情</el-button
                    ></template
                  ></el-table-column
                ></el-table
              >
              <div v-else class="state-panel">
                <el-icon><Search /></el-icon>
                <h2>
                  {{
                    store.messages.length
                      ? "没有符合条件的记录"
                      : "还没有消息记录"
                  }}
                </h2>
                <p>
                  {{
                    store.messages.length
                      ? "调整筛选条件，或从应用、连接重新定位。"
                      : "连接测试后，通知与回复会在这里留下记录。"
                  }}
                </p>
                <el-button v-if="store.messages.length" @click="clearFilters"
                  >清除筛选</el-button
                ><el-button v-else type="primary" @click="go('connections')"
                  >前往通信连接</el-button
                >
              </div>
            </section>
            <p class="page-note">
              平台已接受表示接口未报告错误；不代表手机已收件。结果未知需先核查原投递。
            </p></template
          >
          <template v-else-if="page === 'apps'"
            ><section class="panel">
              <div class="section-title">
                <div>
                  <h2>应用身份与权限</h2>
                  <span>一个调用方使用独立身份；每个身份只调用获准连接。</span>
                </div>
                <el-input
                  v-model="search"
                  :prefix-icon="Search"
                  clearable
                  placeholder="搜索应用"
                  aria-label="搜索应用"
                  class="compact-search"
                />
              </div>
              <el-table v-if="filteredApps.length" :data="filteredApps"
                ><el-table-column label="接入应用" min-width="235"
                  ><template #default="{ row }"
                    ><div class="app-cell">
                      <span class="app-avatar"
                        ><el-icon
                          ><component
                            :is="
                              row.target === 'http' ? Monitor : Grid
                            " /></el-icon
                      ></span>
                      <div>
                        <strong>{{ row.name }}</strong
                        ><small
                          >{{ targetNames[row.target] }} · {{ row.id }}</small
                        >
                      </div>
                    </div></template
                  ></el-table-column
                ><el-table-column label="允许连接 / 默认投递" min-width="255"
                  ><template #default="{ row }"
                    ><span>{{
                      row.bot_ids.map(nameOfBot).join("、") || "未授权连接"
                    }}</span
                    ><small class="block muted"
                      >默认：{{
                        row.default_bot_id
                          ? nameOfBot(row.default_bot_id)
                          : "每次调用显式指定"
                      }}</small
                    ></template
                  ></el-table-column
                ><el-table-column label="状态" width="100"
                  ><template #default="{ row }"
                    ><span
                      :class="['status', row.enabled ? 'ready' : 'disabled']"
                      ><i />{{ row.enabled ? "已启用" : "已停用" }}</span
                    ></template
                  ></el-table-column
                ><el-table-column label="最近调用" width="110"
                  ><template #default="{ row }">{{
                    row.last
                  }}</template></el-table-column
                ><el-table-column label="" width="220"
                  ><template #default="{ row }"
                    ><el-button link type="primary" @click="openConfig(row)"
                      >接入配置</el-button
                    ><el-button link @click="openApp(row)"
                      >权限与默认连接</el-button
                    ></template
                  ></el-table-column
                ></el-table
              >
              <div v-else class="state-panel">
                <el-icon><Grid /></el-icon>
                <h2>
                  {{
                    store.apps.length
                      ? "没有匹配的应用"
                      : "让你的第一个应用接入"
                  }}
                </h2>
                <p>可以是 Codex、Claude Code，也可以是备份任务或业务系统。</p>
                <el-button v-if="store.apps.length" @click="search = ''"
                  >清除搜索</el-button
                ><el-button v-else type="primary" @click="openApp()"
                  >新增接入应用</el-button
                >
              </div>
            </section>
            <div class="soft-note">
              <el-icon><Key /></el-icon>
              <div>
                <strong>密钥属于应用，连接权限属于应用的投递设置。</strong>
                <p>
                  已有密钥只存哈希，不能重新显示；导出配置不会偷偷轮换旧密钥。回复仍按应用、会话与原连接归属。
                </p>
              </div>
            </div></template
          >
          <template v-else-if="page === 'connections'"
            ><div class="filterbar no-panel">
              <el-input
                v-model="search"
                :prefix-icon="Search"
                clearable
                placeholder="搜索连接"
                aria-label="搜索连接"
              /><el-select
                v-model="botFilter"
                clearable
                placeholder="全部平台"
                aria-label="按平台筛选"
                ><el-option label="微信" value="wechat" /><el-option
                  label="飞书"
                  value="feishu"
              /></el-select>
            </div>
            <div v-if="filteredConnections.length" class="connection-cards">
              <section
                v-for="c in filteredConnections"
                :key="c.id"
                class="panel connection-card"
              >
                <div class="connection-card-head">
                  <span class="platform-icon large" :class="c.platform"
                    ><el-icon><ChatLineRound /></el-icon></span
                  ><span :class="['status', !c.enabled ? 'disabled' : c.state]"
                    ><i />{{ !c.enabled ? "已停用" : labels[c.state] }}</span
                  >
                </div>
                <h2>{{ c.name }}</h2>
                <p class="muted">
                  {{
                    c.platform === "wechat" ? "微信 ClawBot" : "飞书应用机器人"
                  }}
                  · {{ c.owner }}
                </p>
                <div class="connection-data">
                  <div>
                    <span>授权应用</span
                    ><strong
                      >{{
                        store.apps.filter((a) => a.bot_ids.includes(c.id))
                          .length
                      }}
                      个</strong
                    >
                  </div>
                  <div>
                    <span>最近入站</span><strong>{{ c.last }}</strong>
                  </div>
                </div>
                <div
                  :class="[
                    'connection-test',
                    { warn: c.test.includes('拒绝') },
                  ]"
                >
                  <el-icon
                    ><component
                      :is="
                        c.test.includes('拒绝') ? Warning : Clock
                      " /></el-icon
                  >{{ c.test }}
                </div>
                <div class="card-actions">
                  <el-button type="primary" plain @click="openConnection(c)">{{
                    c.state === "pending" ? "完成配置" : "管理与测试"
                  }}</el-button
                  ><el-button text @click="toggleConnection(c)">{{
                    c.enabled ? "停用" : "启用"
                  }}</el-button>
                </div>
              </section>
            </div>
            <div v-else class="panel state-panel">
              <el-icon><Connection /></el-icon>
              <h2>
                {{
                  store.connections.length
                    ? "没有匹配的通信连接"
                    : "先连接一个通信平台"
                }}
              </h2>
              <p>微信扫码绑定，飞书配置应用凭据与本人接收账号。</p>
              <el-button
                v-if="store.connections.length"
                @click="
                  search = '';
                  botFilter = '';
                "
                >清除筛选</el-button
              ><el-button v-else type="primary" @click="openConnection()"
                >新增通信连接</el-button
              >
            </div>
            <p class="page-note">
              连接就绪、发送结果与人工收件确认分别记录。停用保留历史；同一平台账号或应用不重复绑定。
            </p></template
          >
          <template v-else-if="page === 'settings'"
            ><div class="section-title">
              <div>
                <h2>选择你要完成的工作</h2>
                <span>三条交付路径，各有清晰入口和资料。</span>
              </div>
            </div>
            <div class="path-cards">
              <section class="panel">
                <span class="action-icon blue"
                  ><el-icon><Monitor /></el-icon
                ></span>
                <h2>部署维护中转站</h2>
                <p>仓库、部署配置、备份与维护说明。Codex 可在站外协助执行。</p>
                <ul>
                  <li>部署准备与配置模板</li>
                  <li>升级前保护与恢复说明</li>
                  <li>维护检查和故障定位</li>
                </ul>
                <el-button @click="openGuide('deploy')"
                  >查看部署维护清单</el-button
                >
              </section>
              <section class="panel">
                <span class="action-icon green"
                  ><el-icon><Grid /></el-icon
                ></span>
                <h2>AI 接入中转站</h2>
                <p>
                  为 Codex / Claude Code 等外部宿主配置 MCP、权限和使用规则。
                </p>
                <ul>
                  <li>远程 MCP 与 OAuth</li>
                  <li>本机 stdio 私有配置</li>
                  <li>宿主接入规则与验收</li>
                </ul>
                <el-button
                  type="primary"
                  plain
                  @click="
                    go('apps');
                    openApp();
                  "
                  >新增 AI 接入应用</el-button
                ><el-button link @click="openGuide('ai')">资料说明</el-button>
              </section>
              <section class="panel">
                <span class="action-icon neutral"
                  ><el-icon><Link /></el-icon
                ></span>
                <h2>业务系统接入通知</h2>
                <p>为后端提供统一 HTTP API、通知、回执和回复读取资料。</p>
                <ul>
                  <li>应用身份与独立 API Key</li>
                  <li>接口文档与调用示例</li>
                  <li>去重、回执和回复规则</li>
                </ul>
                <el-button
                  type="primary"
                  plain
                  @click="
                    go('apps');
                    openApp();
                    appForm.target = 'http';
                  "
                  >新增业务应用</el-button
                ><el-button link @click="openGuide('http')">资料说明</el-button>
              </section>
            </div>
            <section class="panel settings-panel">
              <div class="section-title">
                <h2>服务设置</h2>
                <span>高级配置按需进入</span>
              </div>
              <button @click="openGuide('proxy')">
                <span
                  ><strong>回调代理</strong
                  ><small>订阅、节点、检测与回退；复用现有能力</small></span
                ><el-icon><ArrowRight /></el-icon></button
              ><button @click="openGuide('session')">
                <span
                  ><strong>手机会话登录</strong
                  ><small>本人手机页登录与会话入口</small></span
                ><el-icon><ArrowRight /></el-icon>
              </button>
              <div class="environment">
                <span class="mono">本地原型 / v0.1</span
                ><span>API、数据库与生产配置本轮不变更。</span>
              </div>
            </section></template
          >
        </main>
        <footer class="footer">
          <span>Notify Bridge · 统一收发、路由与记录</span
          ><span>原型 v0.1 · 所有数据均为模拟</span>
        </footer>
      </div>
    </div>
    <el-dialog
      v-model="appDialog"
      :title="appEdit ? '应用权限与默认连接' : '新增接入应用'"
      width="760px"
      :close-on-click-modal="false"
      :before-close="
        (done) => {
          if (!busy) done();
        }
      "
      class="flow-dialog"
      ><el-steps :active="appStep" align-center finish-status="success"
        ><el-step title="应用身份" /><el-step title="允许连接" /><el-step
          title="确认创建"
      /></el-steps>
      <div class="flow-body">
        <template v-if="appStep === 0"
          ><h2>哪个程序需要接入？</h2>
          <p class="muted">身份用来识别消息来源，不在中转站内运行 AI。</p>
          <el-form label-position="top"
            ><el-form-item label="应用名称"
              ><el-input
                v-model="appForm.name"
                maxlength="32"
                placeholder="例如：Codex-运维助手、每日备份任务"
                aria-label="应用名称" /></el-form-item
            ><el-form-item label="接入用途"
              ><div class="choice-grid">
                <button
                  v-for="[id, label, desc] in [
                    ['codex', 'Codex', 'MCP 配置与使用规则'],
                    ['claude', 'Claude Code', '通用 MCP 配置与说明'],
                    ['http', '业务系统', 'HTTP API 与调用示例'],
                  ]"
                  :key="id"
                  :class="['choice', { chosen: appForm.target === id }]"
                  @click.prevent="appForm.target = id"
                >
                  <strong>{{ label }}</strong
                  ><small>{{ desc }}</small>
                </button>
              </div></el-form-item
            ></el-form
          ></template
        ><template v-else-if="appStep === 1"
          ><h2>允许它调用哪些连接？</h2>
          <p class="muted">
            只授权这次需要的连接。默认连接仅决定省略 bot_id 时的投递方向。
          </p>
          <div v-if="!grantChoices.length" class="inline-empty">
            <h3>还没有可用通信连接</h3>
            <p>先添加并配置微信或飞书，再继续这个应用的接入。</p>
            <el-button type="primary" @click="beginConnectionFromApp"
              >先新增通信连接</el-button
            >
          </div>
          <template v-else
            ><el-checkbox-group v-model="appForm.bot_ids" class="grant-options"
              ><el-checkbox
                v-for="c in grantChoices"
                :key="c.id"
                :value="c.id"
                border
                ><strong>{{ c.name }}</strong
                ><small
                  >{{ c.platform === "wechat" ? "微信" : "飞书" }} ·
                  {{
                    !c.enabled
                      ? "已停用"
                      : c.state === "ready"
                        ? "已配置"
                        : "待配置"
                  }}</small
                ></el-checkbox
              ></el-checkbox-group
            ><el-form label-position="top"
              ><el-form-item label="默认投递连接"
                ><el-select
                  v-model="appForm.default_bot_id"
                  clearable
                  placeholder="不设默认，调用方每次指定连接"
                  aria-label="默认投递连接"
                  ><el-option
                    v-for="id in appForm.bot_ids"
                    :key="id"
                    :value="id"
                    :label="nameOfBot(id)"
                /></el-select>
                <p class="help">
                  {{
                    appForm.bot_ids.length === 1 && !appForm.default_bot_id
                      ? "仅一个授权连接时，省略 bot_id 会使用该连接。"
                      : "多个授权连接且无默认值时，调用方必须显式指定 bot_id。"
                  }}
                  不自动广播或切换备用连接。
                </p></el-form-item
              ></el-form
            ></template
          ></template
        ><template v-else
          ><h2>核对应用与投递设置</h2>
          <dl class="summary-list">
            <dt>应用名称</dt>
            <dd>{{ appForm.name }}</dd>
            <dt>接入用途</dt>
            <dd>{{ targetNames[appForm.target] }}</dd>
            <dt>允许连接</dt>
            <dd>{{ appForm.bot_ids.map(nameOfBot).join("、") }}</dd>
            <dt>默认投递</dt>
            <dd>
              {{
                appForm.default_bot_id
                  ? nameOfBot(appForm.default_bot_id)
                  : appForm.bot_ids.length === 1
                    ? "唯一授权连接"
                    : "每次调用指定连接"
              }}
            </dd>
          </dl>
          <div class="soft-note">
            <el-icon><Key /></el-icon>
            <p>
              {{
                appEdit
                  ? "保存不会改变原密钥或历史会话。"
                  : "创建后获得独立身份。API Key 仅在创建时显示；远程 MCP 仍需宿主 OAuth 授权。"
              }}
            </p>
          </div></template
        ><el-alert
          v-if="error"
          :title="error"
          type="error"
          :closable="false"
          show-icon
        />
      </div>
      <template #footer
        ><div class="flow-footer">
          <el-button @click="appDialog = false" :disabled="busy"
            >取消</el-button
          >
          <div>
            <el-button v-if="appStep > 0" @click="appStep--">上一步</el-button
            ><el-button
              v-if="appStep < 2"
              type="primary"
              @click="appNext"
              :disabled="appStep === 1 && !grantChoices.length"
              >下一步</el-button
            ><el-button
              v-else
              type="primary"
              :loading="busy"
              @click="saveApp"
              >{{ appEdit ? "保存权限" : "创建并获取配置" }}</el-button
            >
          </div>
        </div></template
      ></el-dialog
    >
    <el-dialog
      v-model="configDialog"
      title="接入配置与资料"
      @closed="configured && (configured.hasNewKey = false)"
      width="800px"
      class="flow-dialog"
      ><div v-if="configured" class="flow-body">
        <div class="success-heading">
          <span class="action-icon green"
            ><el-icon><CircleCheck /></el-icon
          ></span>
          <div>
            <h2>{{ configured.name }}</h2>
            <p>
              {{
                configured.hasNewKey
                  ? "应用已创建，下一步在调用方完成配置。"
                  : "导出资料不会改变现有身份和权限。"
              }}
            </p>
          </div>
        </div>
        <div class="config-selects">
          <el-select v-model="configTarget" aria-label="资料使用方"
            ><el-option label="Codex" value="codex" /><el-option
              label="Claude Code"
              value="claude" /><el-option
              label="业务系统"
              value="http" /></el-select
          ><el-radio-group v-model="transport"
            ><el-radio-button v-if="configTarget !== 'http'" value="remote"
              >远程 MCP</el-radio-button
            ><el-radio-button v-if="configTarget !== 'http'" value="stdio"
              >本机 stdio</el-radio-button
            ><el-radio-button v-if="configTarget === 'http'" value="http"
              >HTTP API</el-radio-button
            ></el-radio-group
          >
        </div>
        <p v-if="transport === 'remote'" class="help">
          不在资料中携带 API Key。添加远程 MCP
          后由本人在宿主授权；下载不等于接入完成。
        </p>
        <p v-else class="help">
          {{
            configured.hasNewKey
              ? "新建密钥示例：DEMO_KEY_NOT_VALID，仅本次创建可见。"
              : "已有密钥不能回显，示例使用 CONFIGURE_SEPARATELY 占位符。本人需在私有文件中填写原 Key。"
          }}
          私有配置不发给 AI，不提交仓库。
        </p>
        <div class="code-panel">
          <div>
            <span>CONNECTION.example.json</span
            ><el-button text :icon="CopyDocument" @click="copy(configText)"
              >复制</el-button
            >
          </div>
          <pre>{{ configText }}</pre>
        </div>
        <el-alert
          v-if="configTarget === 'claude'"
          title="Claude Code 使用通用 MCP 资料。专用安装格式需在实施时验证，本示例不是可直接安装的插件包。"
          type="info"
          :closable="false"
        /><el-alert
          v-if="exportError"
          :title="exportError"
          type="error"
          :closable="false"
        />
        <div class="config-download">
          <el-button type="primary" :icon="Download" @click="exportConfig"
            >下载演示配置</el-button
          ><el-button
            :icon="Document"
            @click="download(instructions, '接入说明-demo.md')"
            >下载接入说明</el-button
          >
        </div>
        <div class="checklist">
          <h3>在调用方完成最后三步</h3>
          <p><span>1</span>安装或导入配置，完成私有 Key / OAuth 授权。</p>
          <p><span>2</span>登记会话，选择授权连接，使用固定去重键。</p>
          <p><span>3</span>发出经本人允许的测试，由手机收件与回复验收。</p>
        </div>
      </div>
      <template #footer
        ><el-button @click="configDialog = false">完成</el-button></template
      ></el-dialog
    >
    <el-dialog
      v-model="connDialog"
      :title="connEdit ? '管理与测试通信连接' : '新增通信连接'"
      width="800px"
      :close-on-click-modal="false"
      class="flow-dialog"
      ><el-steps :active="connStep" align-center finish-status="success"
        ><el-step title="选择平台" /><el-step
          :title="
            connForm.platform === 'feishu' ? '配置应用' : '扫码绑定'
          " /><el-step title="测试与确认"
      /></el-steps>
      <div class="flow-body">
        <template v-if="connStep === 0"
          ><h2>连接哪个通信平台？</h2>
          <el-form label-position="top"
            ><el-form-item label="连接名称"
              ><el-input
                v-model="connForm.name"
                placeholder="例如：飞书 · 运维通知"
                aria-label="连接名称" /></el-form-item
            ><el-form-item label="平台"
              ><div class="choice-grid two">
                <button
                  :disabled="!!connEdit && connForm.platform !== 'feishu'"
                  :class="[
                    'choice',
                    { chosen: connForm.platform === 'feishu' },
                  ]"
                  @click.prevent="connForm.platform = 'feishu'"
                >
                  <strong>飞书</strong
                  ><small>应用机器人 · HTTPS 回调</small></button
                ><button
                  :class="[
                    'choice',
                    { chosen: connForm.platform === 'wechat' },
                  ]"
                  @click.prevent="connForm.platform = 'wechat'"
                  :disabled="!!connEdit && connForm.platform !== 'wechat'"
                >
                  <strong>微信</strong><small>ClawBot · 扫码绑定本人</small>
                </button>
              </div></el-form-item
            ></el-form
          >
          <p class="help">
            每个连接对应一个独立账号或平台应用。同一上游账号不重复登记。
          </p></template
        ><template v-else-if="connStep === 1 && connForm.platform === 'feishu'"
          ><div class="section-title">
            <div>
              <h2>配置飞书应用</h2>
              <span>先准备应用凭据，再配置事件回调。</span>
            </div>
            <el-button v-if="review" text @click="fillSample"
              >评审：填入示例值</el-button
            >
          </div>
          <el-form label-position="top" class="form-grid"
            ><el-form-item label="App ID"
              ><el-input
                v-model="connForm.app_id"
                :disabled="!!connEdit && connEdit.state === 'ready'"
                placeholder="cli_demo_new"
                aria-label="App ID" /></el-form-item
            ><el-form-item label="本人接收账号 Open ID"
              ><el-input
                v-model="connForm.owner_id"
                :disabled="!!connEdit && connEdit.state === 'ready'"
                placeholder="ou_demo_user"
                aria-label="本人接收账号 Open ID" /></el-form-item
            ><el-form-item label="App Secret"
              ><el-input
                v-model="connForm.app_secret"
                type="password"
                show-password
                :placeholder="connEdit ? '留空保留原凭据' : '仅填写示例值'"
                aria-label="App Secret" /></el-form-item
            ><el-form-item label="Verification Token"
              ><el-input
                v-model="connForm.verification_token"
                type="password"
                show-password
                :placeholder="connEdit ? '留空保留原凭据' : '仅填写示例值'"
                aria-label="Verification Token" /></el-form-item
            ><el-form-item label="Encrypt Key" class="span-two"
              ><el-input
                v-model="connForm.encrypt_key"
                type="password"
                show-password
                :placeholder="connEdit ? '留空保留原凭据' : '仅填写示例值'"
                aria-label="Encrypt Key" /></el-form-item
          ></el-form>
          <p class="help">
            绑定后的应用和本人账号保持固定；新账号请新建连接。空白密码字段保留原值。
          </p></template
        ><template v-else-if="connStep === 1"
          ><h2>在微信确认绑定</h2>
          <p class="muted">使用该连接原来的本人账号。新账号需新建连接。</p>
          <div class="qr-placeholder">
            <el-icon><Connection /></el-icon
            ><strong>{{
              wechatBound
                ? "模拟绑定已完成"
                : qrExpired
                  ? "二维码已过期（演示）"
                  : "扫码图案占位"
            }}</strong
            ><small>本原型没有真实二维码，请勿扫码。</small>
          </div>
          <div class="center-actions">
            <el-button
              v-if="!wechatBound"
              type="primary"
              @click="
                wechatBound = true;
                qrExpired = false;
              "
              >模拟本人扫码确认</el-button
            ><el-button v-if="qrExpired" @click="qrExpired = false"
              >刷新模拟二维码</el-button
            ><el-button v-else-if="!wechatBound" text @click="qrExpired = true"
              >演示二维码过期</el-button
            ><span v-else class="status ready"
              ><i />本人账号已绑定（示例）</span
            >
          </div></template
        ><template v-else
          ><h2>测试连接，并确认手机收件</h2>
          <p class="muted">配置保存、平台接受、真人收件与回复是不同的检查。</p>
          <div v-if="connForm.platform === 'feishu'" class="callback-box">
            <strong>1. 配置事件与卡片回调</strong>
            <p class="help">将同一地址填入事件与回调配置，保存并发布应用。</p>
            <div class="inline-code">
              <code>{{ callbackURL }}</code
              ><el-button text :icon="CopyDocument" @click="copy(callbackURL)"
                >复制</el-button
              >
            </div>
            <el-checkbox v-model="callbackReady"
              >我已完成回调配置与应用发布（模拟）</el-checkbox
            >
          </div>
          <div v-else class="callback-box">
            <strong>1. 刷新微信上下文</strong>
            <p class="help">
              直接在对应 Bot 发一条普通消息；网页回复不会刷新微信上下文。
            </p>
          </div>
          <div class="test-box">
            <div class="section-title">
              <div>
                <strong>2. 发送一条测试通知</strong>
                <p class="help">
                  发送对象：{{
                    connForm.platform === "feishu"
                      ? connForm.owner_id
                      : "本人微信账号"
                  }}
                  · 仅使用当前连接
                </p>
              </div>
              <el-button
                type="primary"
                plain
                :loading="testStatus === 'testing'"
                :disabled="
                  (connForm.platform === 'feishu' && !callbackReady) ||
                  testStatus === 'unknown'
                "
                @click="testConnection"
                >发送模拟测试</el-button
              >
            </div>
            <div v-if="testStatus === 'idle'" class="test-empty">
              尚未发起测试。先完成上面的平台设置。
            </div>
            <div v-else-if="testStatus === 'testing'" class="test-empty">
              正在等待模拟平台结果…
            </div>
            <template v-else
              ><el-alert
                :type="
                  testStatus === 'accepted'
                    ? 'success'
                    : testStatus === 'unknown'
                      ? 'warning'
                      : 'error'
                "
                :title="labels[testStatus]"
                :description="testReceipt.detail"
                :closable="false"
                show-icon
              />
              <div class="mono receipt-line">
                {{ testReceipt.code }} · {{ testReceipt.key }}
              </div>
              <p class="help">{{ testReceipt.next }}</p>
              <el-button
                v-if="testStatus === 'accepted' && !confirmed"
                @click="confirmReceipt"
                >模拟手机已收到并回复</el-button
              ><span v-if="confirmed" class="status ready"
                ><i />人工收件与回复已确认（示例）</span
              ></template
            >
          </div>
          <p v-if="testStatus === 'unknown'" class="danger-note">
            实际测试遇到超时，应查询原回执再决定后续动作。本原型不会自动重发。
          </p></template
        ><el-alert
          v-if="connError"
          :title="connError"
          type="error"
          :closable="false"
          show-icon
        />
      </div>
      <template #footer
        ><div class="flow-footer">
          <el-button
            @click="
              connDialog = false;
              returnToApp = false;
            "
            :disabled="busy"
            >取消</el-button
          >
          <div>
            <el-button v-if="connStep > 0" @click="connStep--" :disabled="busy"
              >上一步</el-button
            ><el-button
              v-if="connStep < 2"
              type="primary"
              :loading="busy"
              @click="connectionNext"
              >{{ connStep === 1 ? "保存并进入测试" : "下一步" }}</el-button
            ><el-button
              v-else
              type="primary"
              :disabled="
                testStatus === 'testing' ||
                (connForm.platform === 'feishu' && !callbackReady)
              "
              @click="finishConnection"
              >{{
                returnToApp ? "保存并返回应用接入" : "保存连接与测试结果"
              }}</el-button
            >
          </div>
        </div></template
      ></el-dialog
    >
    <el-drawer
      v-model="drawer"
      title="通知投递详情"
      size="660px"
      class="detail-drawer"
      ><template v-if="selected"
        ><div class="detail-title">
          <span :class="['status', selected.status]"
            ><i />{{ labels[selected.status] }}</span
          >
          <h2>{{ selected.title }}</h2>
          <p class="muted">{{ selected.at }} · {{ selected.id }}</p>
        </div>
        <dl class="summary-list">
          <dt>接入应用</dt>
          <dd>{{ nameOfApp(selected.app) }}</dd>
          <dt>通信连接</dt>
          <dd>{{ nameOfBot(selected.bot) }}</dd>
          <dt>会话</dt>
          <dd class="mono">{{ selected.cid }}</dd>
          <dt>去重键</dt>
          <dd class="mono">{{ selected.key }}</dd>
        </dl>
        <div class="detail-section">
          <h3>投递经过</h3>
          <div class="timeline">
            <div>
              <i class="done" /><strong>中转站已记录请求</strong>
              <p>保留调用方、原连接、会话与去重键。</p>
            </div>
            <div>
              <i
                :class="
                  selected.code === 'bot_access_denied' ? 'failed' : 'done'
                "
              /><strong>{{
                selected.code === "bot_access_denied"
                  ? "权限校验未通过"
                  : "已向指定平台发起请求"
              }}</strong>
              <p>
                {{
                  selected.code === "bot_access_denied"
                    ? "请求没有交给平台。"
                    : "不自动广播或改投其他连接。"
                }}
              </p>
            </div>
            <div>
              <i :class="selected.status" /><strong>{{
                labels[selected.status]
              }}</strong>
              <p>{{ selected.detail }}</p>
            </div>
          </div>
        </div>
        <div class="diagnostic">
          <div>
            <el-icon
              ><component
                :is="
                  selected.status === 'accepted' ? CircleCheck : Warning
                " /></el-icon
            ><strong>{{
              selected.status === "failed"
                ? "失败原因"
                : selected.status === "unknown"
                  ? "尚未确认的结果"
                  : "当前确认程度"
            }}</strong>
          </div>
          <code
            >{{ selected.code
            }}{{ selected.ret ? " · ret=" + selected.ret : "" }}</code
          >
          <p>{{ selected.detail }}</p>
          <h4>下一步建议</h4>
          <p>{{ selected.next }}</p>
        </div>
        <div class="detail-section">
          <h3>
            回复 <span class="muted">{{ selected.replies.length }} 条</span>
          </h3>
          <div v-for="(r, i) in selected.replies" :key="i" class="reply">
            <span>{{ r.source }} · {{ r.at }}</span>
            <p>{{ r.text }}</p>
          </div>
          <p v-if="!selected.replies.length" class="muted">
            没有关联回复。没有回复不代表通知未到达。
          </p>
        </div>
        <div class="soft-note">
          <el-icon><Document /></el-icon>
          <p>此处为模拟摘要。管理员正文访问范围待确认；原型不提供自动重发。</p>
        </div>
        <el-button
          :icon="CopyDocument"
          @click="
            copy(
              JSON.stringify(
                {
                  message_id: selected.id,
                  app_id: selected.app,
                  bot_id: selected.bot,
                  conversation_id: selected.cid,
                  dedup_key: selected.key,
                  status: selected.status,
                  error_code: selected.code,
                },
                null,
                2,
              ),
            )
          "
          >复制排查信息（不含正文）</el-button
        ></template
      ></el-drawer
    >
    <el-dialog v-model="guideDialog" title="使用与维护资料" width="720px">
      <pre class="guide-text">{{ guideText }}</pre>
      <template #footer
        ><el-button
          :icon="Download"
          @click="download(guideText, 'notify-bridge-demo-guide.md')"
          >下载演示清单</el-button
        ><el-button type="primary" @click="guideDialog = false"
          >关闭</el-button
        ></template
      ></el-dialog
    >
  </el-config-provider>
</template>
