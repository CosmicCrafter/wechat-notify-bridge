<script setup>
import { ref, watch } from "vue";
import { api, session, run } from "../session.js";
import { date } from "../../shared/format.js";
import { receiverLabel } from "../../shared/receiver-state.js";
const props = defineProps({ cid: String });
const emit = defineEmits(["updated"]);
const visible = ref(false),
  data = ref(null),
  host = ref("http"),
  label = ref(""),
  pair = ref(null),
  replace = ref(false),
  role = ref("primary");
async function load() {
  data.value = await api("conversations/" + props.cid + "/receivers");
}
async function open() {
  visible.value = true;
  pair.value = null;
  await run(load);
}
async function issue() {
  const result = await run(() =>
    api("conversations/" + props.cid + "/receiver/pair", {
      host_type: host.value,
      label: label.value,
      replace: replace.value,
      role: role.value,
    }),
  );
  if (result) {
    pair.value = result;
    await load();
    emit("updated");
  }
}
function download() {
  const base = new URL("../", location.href).href.replace(/\/$/, "");
  const blob = new Blob(
    [
      JSON.stringify(
        {
          base_url: base,
          conversation_id: props.cid,
          pairing_code: pair.value.pairing_code,
        },
        null,
        2,
      ),
    ],
    { type: "application/json" },
  );
  const url = URL.createObjectURL(blob),
    link = document.createElement("a");
  link.href = url;
  link.download = "notify-receiver-" + props.cid + ".json";
  link.click();
  URL.revokeObjectURL(url);
}
async function revoke(id) {
  await run(() =>
    api("conversations/" + props.cid + "/receiver/" + id + "/revoke", {}),
  );
  await load();
  emit("updated");
}
watch(
  () => props.cid,
  () => {
    visible.value = false;
    pair.value = null;
    data.value = null;
    replace.value = false;
  },
);
defineExpose({ open });
</script>
<template>
  <el-drawer
    v-model="visible"
    title="会话接收绑定"
    size="560px"
    @closed="pair = null"
    ><p class="help">
      应用 Key 证明应用身份。配对只授予当前会话权限；具体 AI
      聊天身份仍需宿主独立验证。
    </p>
    <el-alert
      v-if="data?.receiver.mode === 'legacy'"
      title="旧模式：同一应用 Key 下的会话没有安全隔离。不会自动撤销旧客户端权限。"
      type="warning"
      :closable="false"
    />
    <template v-else-if="data"
      ><el-descriptions :column="1"
        ><el-descriptions-item label="接收状态">{{
          receiverLabel(data.receiver.status)
        }}</el-descriptions-item
        ><el-descriptions-item label="宿主身份">未验证</el-descriptions-item
        ><el-descriptions-item label="最后权限验证">{{
          date(data.receiver.verified_at)
        }}</el-descriptions-item></el-descriptions
      >
      <div v-for="b in data.bindings" :key="b.id" class="summary-row">
        <div>
          <strong>{{ b.label || "未命名接收端" }}</strong>
          <p class="help">
            {{ b.role === "primary" ? "主处理者" : "只读观察者" }} ·
            {{
              receiverLabel(
                b.expires_at <= Date.now() / 1000 ? "expired" : b.status,
              )
            }}
            · 有效期至 {{ date(b.expires_at) }}
          </p>
        </div>
        <el-button
          v-if="b.status !== 'revoked'"
          type="danger"
          plain
          :disabled="session.busy"
          @click="revoke(b.id)"
          >撤销</el-button
        >
      </div>
      <h3>配对接收端</h3>
      <el-form label-position="top"
        ><el-form-item label="接收方式（声明，不代表已验证）"
          ><el-select v-model="host"
            ><el-option label="HTTP 程序" value="http" /><el-option
              label="Codex"
              value="codex" /><el-option
              label="Claude Code"
              value="claude" /><el-option
              label="ChatGPT Work / Dot"
              value="chatgpt_work" /><el-option
              label="其他 / 未知"
              value="unknown" /></el-select></el-form-item
        ><el-form-item label="接收端名称"
          ><el-input v-model="label" maxlength="80" /></el-form-item
        ><el-form-item label="权限"
          ><el-radio-group v-model="role"
            ><el-radio value="primary">主处理者</el-radio
            ><el-radio value="observer">只读观察者</el-radio></el-radio-group
          ></el-form-item
        ><el-checkbox v-if="role === 'primary'" v-model="replace"
          >撤销已有主绑定并换绑（不代表外部程序已停止）</el-checkbox
        ></el-form
      >
      <el-button type="primary" :loading="session.busy" @click="issue"
        >生成一次性私密配对资料</el-button
      ><el-alert
        v-if="pair"
        title="配对文件仅可使用一次，5 分钟内有效。放入接收端的私有 receiver_file；不要提交仓库或粘贴到 AI 对话。"
        type="warning"
        :closable="false"
      /><el-button v-if="pair" @click="download">下载私密配对文件</el-button>
      <p class="help">
        验证后才可领取。共享接收文件也会共享权限，不能用于不同 AI 聊天。
      </p> </template
    ><el-empty v-else description="正在加载接收状态" />
  </el-drawer>
</template>
