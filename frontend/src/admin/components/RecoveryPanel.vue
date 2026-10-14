<script setup>
import { ref, onBeforeUnmount } from "vue";
import { api, run, session, clearSession } from "../session.js";
import { ElMessage } from "element-plus";
const emit = defineEmits(["back"]);
const username = ref(""),
  platform = ref("wechat"),
  challenge = ref(""),
  code = ref(""),
  password = ref(""),
  confirm = ref("");
async function request() {
  const result = await run(() =>
    api("recovery/request", {
      username: username.value,
      platform: platform.value,
    }),
  );
  if (result) {
    challenge.value = result.challenge_id;
    code.value = "";
  }
}
async function complete() {
  const result = await run(async () => {
    if (password.value !== confirm.value) throw Error("两次新密码不一致。");
    return await api("recovery/complete", {
      challenge_id: challenge.value,
      code: code.value,
      password: password.value,
    });
  });
  if (result) {
    code.value = password.value = confirm.value = "";
    clearSession();
    ElMessage.success("管理密码已更新，请重新登录。");
    emit("back");
  }
}
onBeforeUnmount(() => {
  code.value = password.value = confirm.value = "";
});
</script>
<template>
  <h2>找回管理密码</h2>
  <p class="help">
    只发送到事先绑定并验证的本人微信或飞书。找回页面不能添加新的收件人。
  </p>
  <el-form v-if="!challenge" label-position="top" @submit.prevent="request"
    ><el-form-item label="管理员用户名"
      ><el-input
        v-model="username"
        autocomplete="username"
        maxlength="32" /></el-form-item
    ><el-form-item label="已绑定的恢复平台"
      ><el-radio-group v-model="platform"
        ><el-radio value="wechat">微信</el-radio
        ><el-radio value="feishu">飞书</el-radio></el-radio-group
      ></el-form-item
    ><el-button
      type="primary"
      native-type="submit"
      :loading="session.busy"
      class="full"
      >请求验证码</el-button
    ></el-form
  ><el-form v-else label-position="top" @submit.prevent="complete"
    ><el-alert
      title="若账号与预先验证的连接可用，验证码已尝试发送。请查看对应 Bot；5 分钟有效，最多尝试 5 次。"
      type="info"
      :closable="false"
    /><el-form-item label="8 位恢复验证码"
      ><el-input
        v-model="code"
        autocomplete="one-time-code"
        inputmode="numeric"
        maxlength="8" /></el-form-item
    ><el-form-item label="新密码（15–128 字符）"
      ><el-input
        v-model="password"
        type="password"
        show-password
        autocomplete="new-password"
        maxlength="128" /></el-form-item
    ><el-form-item label="确认新密码"
      ><el-input
        v-model="confirm"
        type="password"
        autocomplete="new-password"
        maxlength="128" /></el-form-item
    ><el-button
      type="primary"
      native-type="submit"
      :loading="session.busy"
      class="full"
      >验证并重置管理密码</el-button
    ><el-button text :disabled="session.busy" @click="challenge = ''"
      >重新请求（至少间隔 60 秒）</el-button
    ></el-form
  ><el-alert
    v-if="session.error"
    :title="session.error"
    type="error"
    :closable="false"
  />
  <p class="help">
    没有可用恢复连接时，请有服务器权限的维护者使用终端重置工具。接入应用
    Key、消息和通信配置会保留。
  </p>
  <el-button text :disabled="session.busy" @click="emit('back')"
    >返回登录</el-button
  >
</template>
