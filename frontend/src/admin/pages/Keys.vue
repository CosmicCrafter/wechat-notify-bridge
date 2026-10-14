<script setup>
import { ref, computed } from "vue";
import { ElMessageBox, ElMessage } from "element-plus";
import GrantsForm from "../components/GrantsForm.vue";
import NotificationPolicy from "../components/NotificationPolicy.vue";
import { session, api, run, refresh, botName, copy } from "../session.js";
import { date } from "../../shared/format.js";
const creating = ref(false),
  editing = ref(false),
  selected = ref(""),
  tab = ref("keys"),
  name = ref(""),
  scope = ref({ bot_ids: [], default_bot_id: null }),
  issued = ref(null),
  rotating = ref(false),
  hours = ref(1),
  q = ref("");
const client = computed(() =>
  session.clients.find((c) => c.id === selected.value),
);
const notificationPolicy = ref();
const clients = computed(() =>
  session.clients.filter((c) => c.name.includes(q.value.trim())),
);
const labels = {
  active: "有效",
  retiring: "迁移中",
  revoked: "已撤销",
  expired: "已到期",
};
function create() {
  name.value = "";
  scope.value = { bot_ids: [], default_bot_id: null };
  creating.value = true;
}
function detail(row) {
  selected.value = row.id;
  tab.value = "keys";
}
async function createApp() {
  const result = await run(async () => {
    if (!name.value.trim()) throw Error("请填写应用名称。");
    const r = await api("clients", {
      name: name.value.trim(),
      key_format: "nb",
      ...scope.value,
    });
    await refresh();
    return r;
  });
  if (result) {
    creating.value = false;
    issued.value = result;
    selected.value = result.client.id;
  }
}
async function editGrants() {
  const result = await run(() => api("clients/" + client.value.id + "/bots"));
  if (result) {
    scope.value = result;
    editing.value = true;
  }
}
async function saveGrants() {
  const result = await run(async () => {
    await api("clients/" + client.value.id + "/bots", scope.value);
    await refresh();
    return true;
  });
  if (result) {
    editing.value = false;
    ElMessage.success("授权已更新。");
  }
}
async function rotate() {
  const result = await run(async () => {
    const r = await api("clients/" + client.value.id + "/credentials/rotate", {
      overlap_seconds: Math.round(hours.value * 3600),
    });
    await refresh();
    return r;
  });
  if (result) {
    rotating.value = false;
    issued.value = result;
  }
}
async function mutate(kind, key) {
  try {
    const current = client.value;
    if (kind === "rename") {
      const r = await ElMessageBox.prompt(
        "应用身份不变，历史会话继续保留。",
        "修改应用名称",
        {
          inputValue: current.name,
          confirmButtonText: "保存",
          cancelButtonText: "取消",
        },
      );
      await run(async () => {
        await api("clients/" + current.id + "/rename", {
          name: r.value.trim(),
        });
        await refresh();
      });
      return;
    }
    const descriptions = {
      finish:
        "确认所有使用旧 Key 的程序已迁移。旧 Key 将立即失效；新 Key 不变。",
      revoke:
        "仅立即撤销这个 Key。使用它的 HTTP/MCP 客户端和回调将失效；独立 OAuth 授权不受影响。若全应用被攻破，请同时停用应用。",
      enabled: current.enabled
        ? "停用此应用后，其全部 Key 与 OAuth 调用不可用；历史消息保留。"
        : "重新启用应用。仍有效的 Key 和 OAuth 授权恢复可用；已撤销的 Key 不会恢复。",
      delete: "永久删除应用身份和凭据，历史消息保留为只读；无法撤销。",
    };
    await ElMessageBox.confirm(
      descriptions[kind],
      kind === "revoke" ? "撤销可能泄露的 Key" : current.name,
      {
        type: "warning",
        confirmButtonText: kind === "revoke" ? "立即撤销" : "确认",
        cancelButtonText: "取消",
      },
    );
    await run(async () => {
      const path =
        kind === "finish"
          ? "credentials/finish"
          : kind === "revoke"
            ? "credentials/" + key.id + "/revoke"
            : kind;
      await api(
        "clients/" + current.id + "/" + path,
        kind === "enabled" ? { enabled: !current.enabled } : {},
      );
      await refresh();
      if (kind === "delete") selected.value = "";
    });
  } catch (e) {
    if (!["cancel", "close"].includes(e)) session.error = e.message;
  }
}
function help() {
  location.hash = "help?app=" + client.value.id;
}
function closeIssued() {
  issued.value = null;
}
</script>
<template>
  <el-card shadow="never"
    ><div class="section-toolbar">
      <div>
        <h2>接入应用</h2>
        <p class="help">
          应用是稳定身份，Key 是可轮换的凭据。每个程序独立授权。
        </p>
      </div>
      <el-button type="primary" @click="create">新增接入应用</el-button>
    </div>
    <el-input
      v-model="q"
      aria-label="搜索接入应用"
      placeholder="按应用名称查找"
      clearable
    /><el-table :data="clients" empty-text="尚无匹配的接入应用"
      ><el-table-column
        prop="name"
        label="应用名称"
        min-width="150"
      /><el-table-column label="状态" min-width="140"
        ><template #default="{ row }"
          ><el-tag :type="row.enabled ? 'success' : 'info'">{{
            row.enabled ? "已启用" : "已停用"
          }}</el-tag>
          <p class="help">
            {{ row.receive_method ? "HTTP / MCP 收件" : "暂无有效接收凭据" }}
          </p></template
        ></el-table-column
      ><el-table-column label="授权连接" min-width="180"
        ><template #default="{ row }"
          >{{ row.bot_ids.map(botName).join("、") || "未授权通信连接" }}
          <p class="help">
            默认：{{
              row.default_bot_id ? botName(row.default_bot_id) : "调用时指定"
            }}
          </p></template
        ></el-table-column
      ><el-table-column label="最近调用" min-width="150"
        ><template #default="{ row }">{{
          date(row.last_seen_at, "尚未调用")
        }}</template></el-table-column
      ><el-table-column label="操作" width="110"
        ><template #default="{ row }"
          ><el-button link type="primary" @click="detail(row)"
            >管理应用</el-button
          ></template
        ></el-table-column
      ></el-table
    ></el-card
  >
  <el-dialog
    :model-value="!!client"
    :title="'接入应用 · ' + (client?.name || '')"
    width="760px"
    @close="selected = ''"
    ><template v-if="client"
      ><p class="help">
        应用 ID：{{ client.id }} · 宿主在线状态未知；最近调用仅表示实际 API
        活动。
      </p>
      <el-tabs v-model="tab"
        ><el-tab-pane label="Key 与凭据" name="keys"
          ><div class="section-toolbar">
            <div>
              <h3>调用 Key</h3>
              <p class="help">
                日常只展示公开标识与掩码。原值丢失时签发新 Key。
              </p>
            </div>
            <el-button
              type="primary"
              :disabled="
                !client.enabled ||
                session.busy ||
                client.credentials.some((k) => k.status === 'retiring')
              "
              @click="
                hours = 1;
                rotating = true;
              "
              >正常轮换 Key</el-button
            >
          </div>
          <div
            v-for="key in client.credentials"
            :key="key.id"
            class="credential-row"
          >
            <div>
              <strong>{{ key.id }}</strong
              ><el-tag
                :type="
                  key.status === 'active'
                    ? 'success'
                    : key.status === 'retiring'
                      ? 'warning'
                      : 'info'
                "
                >{{ labels[key.status] }}</el-tag
              >
              <p class="help">
                {{
                  key.suffix
                    ? "•••• " + key.suffix
                    : "历史 Key，仅保留摘要，末尾未知"
                }}
                · {{ key.format === "nb" ? "nb_ 格式" : "兼容 Key" }}
              </p>
              <p class="help">
                签发 {{ date(key.created_at, "历史签发时间未记录") }} · 最近使用
                {{ date(key.last_used_at, "未记录")
                }}<span v-if="key.expires_at">
                  · 过渡截止 {{ date(key.expires_at) }}</span
                >
              </p>
            </div>
            <el-button
              v-if="['active', 'retiring'].includes(key.status)"
              type="danger"
              link
              :disabled="session.busy"
              @click="mutate('revoke', key)"
              >泄露撤销</el-button
            >
          </div>
          <el-button
            v-if="client.credentials.some((k) => k.status === 'retiring')"
            :disabled="session.busy"
            @click="mutate('finish')"
            >已完成迁移，结束旧 Key</el-button
          >
          <p class="help">
            正常轮换默认允许旧 Key 过渡 1 小时，最多 24 小时。OAuth
            是单独授权，管理密码和 Key 轮换互不替代。
          </p></el-tab-pane
        ><el-tab-pane label="授权连接" name="grants"
          ><p>{{ client.bot_ids.map(botName).join("、") || "未授权连接" }}</p>
          <p class="help">
            默认连接：{{
              client.default_bot_id
                ? botName(client.default_bot_id)
                : "调用时指定"
            }}
          </p>
          <el-button @click="editGrants">编辑授权</el-button></el-tab-pane
        ><el-tab-pane label="通知分流" name="notifications">
          <h3>普通与紧急提醒</h3>
          <p class="help">
            为未指定目标的通知选择默认连接，按会话设置偏好，并单独授权紧急飞书
            B。
          </p>
          <el-button @click="notificationPolicy.open()"
            >配置通知分流</el-button
          > </el-tab-pane
        ><el-tab-pane label="接入资料" name="exports"
          ><h3>为这个应用导出配置</h3>
          <p class="help">
            Codex、Claude Code 和 HTTP
            系统共用这个应用身份；导出不新建身份、不自动轮换
            Key。需使用你已保存的有效 Key，不能从服务端恢复原值。
          </p>
          <el-button type="primary" @click="help"
            >打开接入向导</el-button
          ></el-tab-pane
        ></el-tabs
      >
      <div class="actions">
        <el-button @click="mutate('rename')">修改名称</el-button
        ><el-button @click="mutate('enabled')">{{
          client.enabled ? "停用应用" : "启用应用"
        }}</el-button
        ><el-button type="danger" text @click="mutate('delete')"
          >删除应用</el-button
        >
      </div></template
    ></el-dialog
  >
  <el-dialog
    v-model="creating"
    title="新增接入应用"
    width="560px"
    :close-on-click-modal="false"
    ><el-form label-position="top"
      ><el-form-item label="应用名称" required
        ><el-input
          v-model="name"
          maxlength="32"
          placeholder="例如 codex、开票程序" /></el-form-item></el-form
    ><GrantsForm v-model="scope" /><template #footer
      ><el-button :disabled="session.busy" @click="creating = false"
        >取消</el-button
      ><el-button type="primary" :loading="session.busy" @click="createApp"
        >创建应用并签发 Key</el-button
      ></template
    ></el-dialog
  >
  <el-dialog
    v-model="editing"
    title="编辑应用授权"
    width="560px"
    :close-on-click-modal="false"
    ><GrantsForm v-model="scope" />
    <p class="help">保存后立即生效；应用与 Key 身份不变。</p>
    <template #footer
      ><el-button :disabled="session.busy" @click="editing = false"
        >取消</el-button
      ><el-button type="primary" :loading="session.busy" @click="saveGrants"
        >保存授权</el-button
      ></template
    ></el-dialog
  >
  <el-dialog
    v-model="rotating"
    title="正常轮换 Key"
    width="480px"
    :close-on-click-modal="false"
    ><p>先签发新 Key、更新调用方，再结束旧 Key。过渡到期后旧 Key 自动失效。</p>
    <el-form label-position="top"
      ><el-form-item label="旧 Key 过渡时间（小时）"
        ><el-input-number
          v-model="hours"
          :min="0"
          :max="24"
          :step="1" /></el-form-item
    ></el-form>
    <p class="help">
      选择 0 小时会立即结束旧 Key。确认泄露时先撤销受影响 Key。
    </p>
    <template #footer
      ><el-button :disabled="session.busy" @click="rotating = false"
        >取消</el-button
      ><el-button type="primary" :loading="session.busy" @click="rotate"
        >签发新 Key</el-button
      ></template
    ></el-dialog
  >
  <el-dialog
    :model-value="!!issued"
    title="一次展示 · 保存接入凭据"
    width="600px"
    :close-on-click-modal="false"
    @close="closeIssued"
    ><template v-if="issued"
      ><el-alert
        title="关闭后不会再次显示完整 Key。请保存到调用方私有配置。"
        type="warning"
        :closable="false"
      />
      <p>应用：{{ issued.client.name }} · Key ID：{{ issued.credential.id }}</p>
      <el-form label-position="top"
        ><el-form-item label="新 Key"
          ><el-input :model-value="issued.api_key" readonly
            ><template #append
              ><el-button @click="copy(issued.api_key)"
                >复制</el-button
              ></template
            ></el-input
          ></el-form-item
        ><el-form-item label="接入配置"
          ><el-input
            type="textarea"
            :rows="5"
            :model-value="
              JSON.stringify(
                {
                  base_url: issued.base_url,
                  api_key: issued.api_key,
                  client_id: issued.client.id,
                  key_id: issued.credential.id,
                },
                null,
                2,
              )
            "
            readonly /></el-form-item
      ></el-form>
      <p v-if="issued.overlap_seconds !== undefined" class="help">
        旧 Key 过渡
        {{ issued.overlap_seconds / 3600 }} 小时。迁移结束后在应用详情结束旧
        Key。
      </p></template
    ><template #footer
      ><el-button type="primary" @click="closeIssued"
        >已保存，关闭</el-button
      ></template
    ></el-dialog
  >
  <NotificationPolicy
    v-if="client"
    ref="notificationPolicy"
    :client-id="client.id"
  />
</template>
