<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from "vue";
import { api, run, session, refresh } from "../session.js";
import { ElMessage } from "element-plus";
import { date } from "../../shared/format.js";
const props = defineProps({ account: Object });
const emit = defineEmits(["updated"]);
const bindings = ref([]),
  dialog = ref(false),
  kind = ref("bind"),
  bot = ref(""),
  old = ref(""),
  code = ref(""),
  challenge = ref("");
const choices = computed(() =>
  session.bots.filter(
    (b) => b.enabled && (b.status.bound || b.status.configured),
  ),
);
function protectedBinding(b) {
  return !bindings.value.some(
    (other) => other.bot_id !== b.bot_id && other.valid,
  );
}
async function load() {
  try {
    bindings.value = (await api("account/recovery")).bindings;
  } catch (e) {
    session.error = e.message;
  }
}
function open(type, id = "") {
  kind.value = type;
  bot.value = id;
  old.value = code.value = challenge.value = "";
  dialog.value = true;
}
async function submit() {
  const result = await run(async () => {
    if (kind.value === "bind") {
      if (challenge.value)
        return await api("account/recovery/verify", {
          challenge_id: challenge.value,
          code: code.value,
        });
      return await api("account/recovery/bind", {
        bot_id: bot.value,
        old_password: old.value,
      });
    }
    if (kind.value === "remove")
      return await api("account/recovery/" + bot.value + "/remove", {
        old_password: old.value,
        enabled: false,
      });
    return await api("account/legacy-key", {
      old_password: old.value,
      enabled: !props.account.legacy_enabled,
    });
  });
  old.value = "";
  if (!result) return;
  if (result.challenge_id) {
    challenge.value = result.challenge_id;
    ElMessage.info("请查看所选本人 Bot 的验证码。");
    return;
  }
  dialog.value = false;
  code.value = "";
  if (kind.value === "legacy") emit("updated", result);
  await load();
  await refresh();
  ElMessage.success("恢复设置已更新。");
}
onMounted(load);
onBeforeUnmount(() => {
  old.value = code.value = "";
});
</script>
<template>
  <el-card shadow="never"
    ><div class="section-toolbar">
      <div>
        <h2>管理员恢复连接</h2>
        <p class="help">
          先收到并验证验证码，再建立保护。最后一个已验证连接不能在站内停用、删除或替换。
        </p>
      </div>
      <el-button type="primary" :disabled="session.busy" @click="open('bind')"
        >绑定恢复连接</el-button
      >
    </div>
    <el-empty
      v-if="!bindings.length"
      description="尚无已验证恢复连接，请先绑定本人微信或飞书"
    />
    <div v-for="b in bindings" :key="b.bot_id" class="summary-row">
      <div>
        <strong>{{ b.name }}</strong
        ><el-tag :type="b.valid ? 'success' : 'warning'">{{
          b.valid ? "已验证" : "当前不可用"
        }}</el-tag>
        <p class="help">
          验证于 {{ date(b.verified_at) }} ·
          {{
            protectedBinding(b) ? "最后恢复连接，受保护" : "已具备其他恢复连接"
          }}
        </p>
      </div>
      <el-button
        :disabled="protectedBinding(b) || session.busy"
        @click="open('remove', b.bot_id)"
        >解除绑定</el-button
      >
    </div></el-card
  ><el-card shadow="never"
    ><h2>原管理 Key 迁移</h2>
    <p class="help">
      {{
        account.legacy_enabled
          ? "原管理 Key 仍可进入管理端。建议账号登录和恢复验证完成后显式停用。"
          : "原管理 Key 已停用，管理端使用账号会话。"
      }}
    </p>
    <el-button
      :disabled="session.busy || !session.csrf"
      @click="open('legacy')"
      >{{
        account.legacy_enabled ? "停用原管理 Key" : "重新启用原管理 Key"
      }}</el-button
    >
    <p v-if="!session.csrf" class="help">
      请先使用账号密码登录，再操作旧管理 Key。
    </p>
    <p class="help">此设置只控制旧管理 Key，不影响应用调用 Key。</p></el-card
  ><el-card shadow="never"
    ><h2>服务器终端兜底</h2>
    <p class="help">
      丢失所有恢复方式时，由获授权且有服务器文件权限的维护者执行
      <code>python -m wechat_bridge.admin_reset</code>。工具先做 SQLite
      一致快照，再交互读取新密码，仅重置管理账号与会话。完整操作见“帮助与接入”的维护说明。
    </p></el-card
  >
  <el-dialog
    v-model="dialog"
    :title="
      kind === 'bind'
        ? '验证并绑定本人恢复连接'
        : kind === 'remove'
          ? '解除旧恢复连接'
          : '迁移原管理 Key'
    "
    width="500px"
    :close-on-click-modal="false"
    @closed="old = code = challenge = ''"
  >
    <el-form label-position="top" @submit.prevent="submit"
      ><template v-if="kind === 'bind'"
        ><el-form-item v-if="!challenge" label="已配置的本人通信连接"
          ><el-select v-model="bot" aria-label="管理员恢复连接"
            ><el-option
              v-for="b in choices"
              :key="b.id"
              :value="b.id"
              :label="b.name" /></el-select
        ></el-form-item>
        <p class="help">
          收件人来自该连接的既有本人绑定。不会在找回页面临时改收件人。
        </p>
        <el-form-item v-if="challenge" label="8 位绑定验证码"
          ><el-input
            v-model="code"
            maxlength="8"
            inputmode="numeric"
            autocomplete="one-time-code" /></el-form-item></template
      ><el-form-item v-if="!challenge" label="当前管理密码"
        ><el-input
          v-model="old"
          type="password"
          show-password
          autocomplete="current-password" /></el-form-item></el-form
    ><template #footer
      ><el-button :disabled="session.busy" @click="dialog = false"
        >取消</el-button
      ><el-button type="primary" :loading="session.busy" @click="submit">{{
        kind === "bind"
          ? challenge
            ? "验证并绑定"
            : "发送绑定验证码"
          : "确认更新"
      }}</el-button></template
    ></el-dialog
  >
</template>
