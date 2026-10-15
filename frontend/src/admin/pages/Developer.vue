<script setup>
import {
  ref,
  computed,
  watch,
  onMounted,
  onBeforeUnmount,
  nextTick,
} from "vue";
import { api, run, session, refresh } from "../session.js";
import Markdown from "../../shared/Markdown.vue";
import { ElMessage } from "element-plus";
const docs = ref(null),
  metadata = ref(null),
  tab = ref("quick"),
  reference = ref("guide"),
  step = ref(0);
const referenceBase = computed(() => {
  const source =
    docs.value?._sources?.[reference.value] || "docs/integration/README.md";
  return (
    "https://github.com/CosmicCrafter/wechat-notify-bridge/blob/main/" +
    source.slice(0, source.lastIndexOf("/") + 1)
  );
});
const target = ref("codex"),
  transport = ref("remote"),
  credentialMode = ref("existing");
const clientId = ref(""),
  clientName = ref(""),
  botId = ref(""),
  key = ref(""),
  privateAck = ref(false);
const savedUrl = ref(""),
  failed = ref(false);
const selectedClient = computed(() =>
  session.clients.find((c) => c.id === clientId.value),
);
const activeClients = computed(() => session.clients.filter((c) => c.enabled));
const choices = computed(() =>
  session.bots.filter(
    (b) =>
      b.enabled &&
      (credentialMode.value === "new" ||
        selectedClient.value?.bot_ids?.includes(b.id)),
  ),
);
const selectedBot = computed(() =>
  session.bots.find((b) => b.id === botId.value),
);
const ready = computed(
  () =>
    !!botId.value &&
    (credentialMode.value === "new"
      ? /^[a-zA-Z0-9_\-\u4e00-\u9fff]{1,32}$/.test(clientName.value)
      : !!selectedClient.value &&
        (transport.value === "remote" || !!key.value)),
);
function clearDownload() {
  if (savedUrl.value) URL.revokeObjectURL(savedUrl.value);
  savedUrl.value = "";
}
watch([clientId, credentialMode], () => {
  botId.value = "";
  key.value = "";
  privateAck.value = false;
});
watch([target, transport], () => {
  key.value = "";
  privateAck.value = false;
});
let alive = true;
const loadError = ref("");
async function load() {
  loadError.value = "";
  try {
    const [data, connection] = await Promise.all([
      api("developer-docs"),
      api("onboarding"),
    ]);
    if (!alive) return;
    docs.value = data;
    metadata.value = connection;
    if (!connection.remote_available) transport.value = "local";
    const expected = new URLSearchParams(location.hash.split("?")[1] || "").get(
      "app",
    );
    if (expected && activeClients.value.some((c) => c.id === expected)) {
      clientId.value = expected;
      credentialMode.value = "existing";
      await nextTick();
      botId.value =
        selectedClient.value.default_bot_id ||
        (choices.value.length === 1 ? choices.value[0].id : "");
    }
  } catch (e) {
    if (alive && !e.stale) loadError.value = e.message;
  }
}
onMounted(load);
onBeforeUnmount(() => {
  alive = false;
  clearDownload();
  key.value = "";
});
function save(url, filename) {
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
}
function next() {
  if (step.value === 0 && target.value === "chatgpt")
    transport.value = "remote";
  if (target.value === "http") transport.value = "local";
  if (
    step.value === 1 &&
    transport.value === "remote" &&
    !metadata.value?.remote_available
  ) {
    ElMessage.warning("远程 MCP 需要可访问的 HTTPS 地址。");
    return;
  }
  if (step.value === 2 && !ready.value) {
    ElMessage.warning("请完善身份、Bot 和必要的 Key。");
    return;
  }
  step.value++;
}
function generate() {
  run(async () => {
    clearDownload();
    failed.value = false;
    try {
      const blob = await api(
        "onboarding/package",
        {
          kind: "configured",
          transport: transport.value,
          target: target.value,
          credential_mode: credentialMode.value,
          client_id: clientId.value,
          client_name: clientName.value,
          bot_id: botId.value,
          api_key:
            transport.value === "local" && credentialMode.value === "existing"
              ? key.value
              : "",
          private_ack: privateAck.value,
          key_format: "nb",
        },
        true,
      );
      if (!alive) return;
      savedUrl.value = URL.createObjectURL(blob);
      key.value = "";
      step.value = 4;
      save(
        savedUrl.value,
        "notify-bridge-" + transport.value + "-configured.zip",
      );
      ElMessage.success("文件已生成，请从 START-HERE.md 开始。");
      await refresh();
    } catch (e) {
      failed.value = true;
      throw e;
    }
  });
}
function download(kind, mode = transport.value) {
  run(async () => {
    const blob =
      kind === "docs"
        ? await api("developer-kit", undefined, true)
        : await api(
            "onboarding/package",
            {
              kind,
              transport: mode,
              target:
                kind === "rules"
                  ? "generic"
                  : mode === "local"
                    ? "generic"
                    : target.value,
            },
            true,
          );
    const url = URL.createObjectURL(blob);
    save(
      url,
      "notify-bridge-" +
        kind +
        (kind === "template" ? "-" + mode : "") +
        ".zip",
    );
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  });
}
function reset() {
  clearDownload();
  step.value = 0;
  key.value = "";
  privateAck.value = false;
  clientName.value = "";
  clientId.value = "";
  botId.value = "";
  failed.value = false;
}
</script>
<template>
  <div class="developer-intro">
    <div class="stats delivery-paths">
      <el-card shadow="never"
        ><h3>部署与维护自己的站</h3>
        <p class="help">版本、环境、升级备份和终端恢复。</p>
        <el-button
          @click="
            tab = 'api';
            reference = 'operations';
          "
          >维护说明</el-button
        ></el-card
      ><el-card shadow="never"
        ><h3>AI 接入中转站</h3>
        <p class="help">Codex / Claude Code MCP，复用已有应用与授权。</p>
        <el-button
          @click="
            tab = 'quick';
            target = 'codex';
            step = 0;
          "
          >AI 接入向导</el-button
        ></el-card
      ><el-card shadow="never"
        ><h3>业务系统接入通知</h3>
        <p class="help">直接 HTTP 与轻量客户端，固定身份、消息和回执。</p>
        <el-button
          @click="
            tab = 'quick';
            target = 'http';
            transport = 'local';
            step = 0;
          "
          >HTTP 接入向导</el-button
        ></el-card
      >
    </div>
    <h2>把通知桥接入你的 AI 或程序</h2>
    <p class="help">
      选择接入方式，下载配置与使用规则。连接、消息送达和自动唤醒分别验收。
    </p>
    <a href="../docs/" target="_blank" rel="noopener noreferrer"
      >公开开发文档 · 可直接分享给接入者，无需管理登录</a
    >
    <p v-if="docs?._release" class="help">
      资料：服务 {{ docs._release.server_version }} · 插件
      {{ docs._release.plugin_version }}。安装与配置以包内 INSTALL.md /
      README.md 为准。
    </p>
  </div>
  <el-tabs v-model="tab"
    ><el-tab-pane label="快速接入" name="quick" /><el-tab-pane
      label="手动配置"
      name="manual" /><el-tab-pane label="接口文档" name="api"
  /></el-tabs>
  <el-card v-if="tab === 'quick'" shadow="never" class="onboarding-card">
    <el-steps
      :active="step"
      finish-status="success"
      align-center
      class="onboarding-steps"
      ><el-step title="选客户端" /><el-step title="选连接方式" /><el-step
        title="身份与 Bot" /><el-step title="下载与安装" /><el-step
        title="验证连接"
    /></el-steps>
    <div class="onboarding-body">
      <template v-if="step === 0"
        ><h3>你要接入哪个客户端？</h3>
        <el-radio-group v-model="target" class="onboarding-options"
          ><el-radio value="codex" border>Codex</el-radio
          ><el-radio value="chatgpt" border>网页 ChatGPT</el-radio
          ><el-radio value="claude" border>Claude Code</el-radio
          ><el-radio value="http" border>HTTP 业务系统</el-radio
          ><el-radio value="generic" border
            >其他 MCP 客户端</el-radio
          ></el-radio-group
        >
        <p class="help">
          Codex 可选择插件安装或直接配置
          MCP；其他宿主按实际支持的格式导入。并非所有客户端都支持 ZIP 插件。
        </p>
      </template>
      <template v-else-if="step === 1"
        ><h3>选择连接方式</h3>
        <el-alert
          v-if="target === 'http'"
          title="业务系统直接通过 HTTP 调用。包内提供私有配置、OpenAPI 和 Python 示例，无需安装 MCP。"
          type="info"
          :closable="false"
        />
        <el-radio-group v-else v-model="transport" class="onboarding-options"
          ><el-radio
            value="remote"
            border
            :disabled="!metadata?.remote_available"
            >远程 MCP · OAuth</el-radio
          ><el-radio value="local" border :disabled="target === 'chatgpt'"
            >本机插件 · stdio</el-radio
          ></el-radio-group
        >
        <el-alert
          v-if="transport === 'remote'"
          title="无需本机 Python；用户仍需在宿主中完成 OAuth 授权。包内不会包含访问令牌或 API Key。"
          type="info"
          :closable="false"
        />
        <el-alert
          v-else-if="target !== 'http'"
          title="需要 Python 3.12+。包内包含私有连接配置，解压后先准备运行环境，再安装或导入 MCP。"
          type="info"
          :closable="false"
        />
        <p class="help" v-if="!metadata?.remote_available">
          当前未配置公共 HTTPS
          地址，仅能生成本机接入包。网页客户端无法访问你电脑的 localhost。
        </p>
      </template>
      <template v-else-if="step === 2"
        ><h3>确定身份与默认 Bot</h3>
        <el-radio-group v-model="credentialMode" class="onboarding-options"
          ><el-radio value="existing">使用已有应用（推荐）</el-radio
          ><el-radio value="new">新增专用应用</el-radio></el-radio-group
        >
        <el-form label-position="top" class="onboarding-form">
          <el-form-item
            v-if="credentialMode === 'new'"
            label="新身份名称"
            required
            ><el-input
              v-model="clientName"
              maxlength="32"
              placeholder="例如 codex-开票助手"
            />
            <p class="help">
              下载时才创建，仅授权下面所选的一个 Bot；不影响旧 Key。
            </p></el-form-item
          >
          <el-form-item v-else label="客户端身份" required
            ><el-select v-model="clientId" placeholder="选择已有身份" filterable
              ><el-option
                v-for="client in activeClients"
                :key="client.id"
                :label="client.name"
                :value="client.id" /></el-select
          ></el-form-item>
          <el-form-item label="默认使用的 Bot" required
            ><el-select
              v-model="botId"
              placeholder="选择已启用且有权限的 Bot"
              filterable
              ><el-option
                v-for="bot in choices"
                :key="bot.id"
                :label="
                  bot.name +
                  ' · ' +
                  (bot.platform === 'wechat' ? '微信' : '飞书')
                "
                :value="bot.id" /></el-select
          ></el-form-item>
          <el-form-item
            v-if="credentialMode === 'existing' && transport === 'local'"
            label="该身份的原 Key"
            required
            ><el-input
              v-model="key"
              type="password"
              show-password
              autocomplete="off"
              placeholder="仅在此页面校验并打包，不发送给 AI"
            />
            <p class="help">
              服务器仅保存哈希，无法取回旧
              Key。不知道原值时，请到该应用管理页正常轮换；导出不会自动换 Key
              或复制身份。
            </p></el-form-item
          >
        </el-form>
        <el-alert
          v-if="credentialMode === 'existing'"
          type="warning"
          :closable="false"
          title="不会更改已有身份的权限或服务器默认 Bot。包内默认值只是路由偏好，其他已授权 Bot 仍可调用。"
        />
        <p v-if="selectedClient && credentialMode === 'existing'" class="help">
          已有授权：{{
            selectedClient.bot_ids
              .map((id) => session.bots.find((b) => b.id === id)?.name || id)
              .join("、") || "无"
          }}
        </p>
      </template>
      <template v-else-if="step === 3"
        ><h3>确认下载内容</h3>
        <el-descriptions :column="1" border
          ><el-descriptions-item label="接入方式">{{
            transport === "remote"
              ? "远程 MCP · 需要 OAuth 授权"
              : target === "http"
                ? "HTTP 业务系统 · 私有配置"
                : "本机 stdio · 需要 Python 3.12+"
          }}</el-descriptions-item
          ><el-descriptions-item label="客户端身份">{{
            credentialMode === "new"
              ? clientName + "（将新建）"
              : selectedClient?.name
          }}</el-descriptions-item
          ><el-descriptions-item label="默认 Bot">{{
            selectedBot?.name
          }}</el-descriptions-item
          ><el-descriptions-item label="包内内容"
            >{{
              target === "http"
                ? "HTTP 示例、OpenAPI、连接说明及私有配置"
                : "Skill、连接说明、安装步骤、MCP 配置"
            }}{{
              transport === "local" && target !== "http"
                ? "、适配器与私有 Key"
                : ""
            }}</el-descriptions-item
          ></el-descriptions
        >
        <el-alert
          v-if="transport === 'remote'"
          type="info"
          :closable="false"
          title="授权时请主动选择上述身份。下载包不能跳过 OAuth 或强制替用户完成授权。"
        />
        <el-checkbox v-else v-model="privateAck" class="private-ack"
          >我知道这是含 Key 的私有包，只交给被授权用户，不上传仓库或发送到 AI
          聊天。</el-checkbox
        >
        <el-alert
          v-if="failed"
          type="warning"
          :closable="false"
          title="本次下载结果未确认。若选择了新建身份，请先查看接入密钥列表是否已创建，不要反复创建或重置其他 Key。"
        />
      </template>
      <template v-else
        ><h3>接入包已生成</h3>
        <template v-if="target === 'http'"
          ><p>
            解压后先读 START-HERE.md 和 notify-bridge-http/README.md，无需安装
            MCP 或插件。
          </p>
          <el-timeline
            ><el-timeline-item
              >GET /api/status
              核对应用身份与授权；读取包内私有配置，不在日志打印
              Key。</el-timeline-item
            ><el-timeline-item
              >按固定业务事件登记会话，用原键发送通知并查询投递回执。</el-timeline-item
            ><el-timeline-item
              >按会话读取 /api/inbox，显式 claim，再 report
              实际处理结果并继续回复。</el-timeline-item
            ></el-timeline
          ></template
        >
        <template v-else
          ><p>
            解压后先读 <code>START-HERE.md</code>，安装细节在插件目录的
            <code>INSTALL.md</code>。
          </p>
          <el-timeline
            ><el-timeline-item
              >连接检查：调用 getCallerIdentity，核对身份与授权
              Bot，不发送消息。</el-timeline-item
            ><el-timeline-item
              >通知检查：用户明确确认后，登记当前会话、dry_run，再发送测试消息并核对真人收件。</el-timeline-item
            ><el-timeline-item
              >回复检查：在对应 Bot 回复，再用 getMessages
              读取；自动唤醒需要额外配置。</el-timeline-item
            ></el-timeline
          >
        </template>
        <el-button
          :disabled="!savedUrl"
          @click="
            save(savedUrl, 'notify-bridge-' + transport + '-configured.zip')
          "
          >重新下载同一份包</el-button
        ><el-button text @click="tab = 'manual'">查看完整配置说明</el-button>
        <p class="help">
          文件仅在本页内存中保留；服务器不能反查 Key
          原值。生成包不改变已有应用或 Key，也不代表已经连通。
        </p>
      </template>
    </div>
    <div class="onboarding-footer">
      <el-button
        v-if="step > 0 && step < 4"
        :disabled="session.busy"
        @click="step--"
        >上一步</el-button
      ><el-button
        v-if="step < 3"
        type="primary"
        :disabled="!metadata || session.busy || (step === 2 && !ready)"
        @click="next"
        >下一步</el-button
      ><el-button
        v-else-if="step === 3"
        type="primary"
        :loading="session.busy"
        :disabled="transport === 'local' && !privateAck"
        @click="generate"
        >{{
          credentialMode === "new" ? "创建专用身份并下载" : "生成并下载接入包"
        }}</el-button
      ><el-button v-else @click="reset">配置另一个客户端</el-button>
    </div>
  </el-card>
  <template v-else-if="tab === 'manual'">
    <el-card shadow="never"
      ><h3>自行配置与规则包</h3>
      <p class="help">
        模板不含真实 Key；仅规则包不包含 MCP 连接。选择与你宿主能力匹配的方式。
      </p>
      <div class="actions">
        <el-button
          :disabled="session.busy"
          @click="download('template', 'local')"
          >本机接入模板</el-button
        ><el-button
          :disabled="session.busy || !metadata?.remote_available"
          @click="download('template', 'remote')"
          >远程接入模板</el-button
        ><el-button :disabled="session.busy" @click="download('rules')"
          >仅下载 Skill 规则</el-button
        >
      </div></el-card
    >
    <el-card shadow="never" class="developer-guide"
      ><Markdown
        v-if="docs"
        :text="docs.setup || ''"
        :base="'https://github.com/CosmicCrafter/wechat-notify-bridge/blob/main/docs/integration/'"
    /></el-card>
  </template>
  <el-card v-else shadow="never"
    ><div class="section-toolbar">
      <div>
        <h3>程序与 AI 开发接口</h3>
        <p class="help">已有程序可直接调用 HTTP API，不必安装 Skill。</p>
      </div>
      <el-button :loading="session.busy" @click="download('docs')"
        >下载接入文档包</el-button
      >
    </div>
    <el-tabs v-model="reference"
      ><el-tab-pane label="部署与恢复" name="operations" /><el-tab-pane
        label="AI 宿主接入"
        name="ai" /><el-tab-pane
        label="HTTP 业务闭环"
        name="http" /><el-tab-pane label="接入指南" name="guide" /><el-tab-pane
        label="HTTP 接口"
        name="api" /><el-tab-pane label="任务卡片" name="cards" /></el-tabs
    ><Markdown v-if="docs" :text="docs[reference] || ''" :base="referenceBase"
  /></el-card>
</template>
<style scoped>
.delivery-paths {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}
@media (max-width: 680px) {
  .delivery-paths {
    grid-template-columns: minmax(0, 1fr);
  }
}
.developer-intro {
  margin-bottom: 20px;
}
.onboarding-card {
  max-width: 1040px;
}
.onboarding-steps {
  margin: 12px 0 28px;
}
.onboarding-body {
  max-width: 720px;
  min-height: 220px;
  margin: 0 auto;
}
.onboarding-body h3 {
  margin-bottom: 22px;
}
.onboarding-options {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 24px;
}
.onboarding-options .el-radio {
  margin: 0;
}
.onboarding-form {
  margin-top: 20px;
}
.onboarding-footer {
  border-top: 1px solid var(--el-border-color-lighter);
  padding-top: 20px;
  margin-top: 28px;
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.onboarding-body .el-alert {
  margin-top: 18px;
}
.private-ack {
  margin-top: 24px;
  height: auto;
  white-space: normal;
  align-items: flex-start;
}
.developer-guide {
  margin-top: 20px;
}
@media (max-width: 600px) {
  .onboarding-steps :deep(.el-step__title) {
    font-size: 11px;
  }
  .onboarding-body {
    min-height: 180px;
  }
  .onboarding-options {
    flex-direction: column;
    align-items: stretch;
  }
  .onboarding-options .el-radio.is-bordered {
    height: 48px;
  }
  .private-ack :deep(.el-checkbox__label) {
    white-space: normal;
    line-height: 1.6;
  }
}
</style>
