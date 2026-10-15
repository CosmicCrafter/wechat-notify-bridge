<script setup>
import { ref } from "vue";
import { session, run, loginAccount } from "../session.js";
import RecoveryPanel from "./RecoveryPanel.vue";
import TerminalRecovery from "./TerminalRecovery.vue";
const username = ref(""),
  password = ref(""),
  mode = ref("password");
async function login() {
  const ok = await run(async () => {
    if (!username.value || !password.value) throw Error("请填写用户名和密码。");
    const value = password.value;
    password.value = "";
    await loginAccount(username.value, value);
    return true;
  });
  if (ok) session.authenticated = true;
}
</script>
<template>
  <div class="login-page">
    <div class="login-brand">↗</div>
    <h1>Notify Bridge</h1>
    <p>统一消息中转站</p>
    <el-card shadow="never" class="login-card">
      <RecoveryPanel
        v-if="mode === 'recovery'"
        @back="
          mode = 'password';
          session.error = '';
        "
      />
      <template v-else>
        <h2>登录管理中心</h2>
        <p class="help">管理消息、应用与通信连接。</p>
        <el-alert
          v-if="!session.configured"
          title="尚未建立管理员账号，请由获授权的维护者使用服务器终端工具初始化。"
          type="info"
          :closable="false"
        />
        <TerminalRecovery v-if="!session.configured" initialize />
        <el-form label-position="top" @submit.prevent="login">
          <el-form-item label="用户名"
            ><el-input
              v-model="username"
              autocomplete="username"
              maxlength="32"
          /></el-form-item>
          <el-form-item label="密码"
            ><el-input
              v-model="password"
              type="password"
              show-password
              autocomplete="current-password"
              maxlength="128"
          /></el-form-item>
          <el-button
            type="primary"
            native-type="submit"
            :loading="session.busy"
            :disabled="!session.configured"
            class="full"
            >登录</el-button
          >
        </el-form>
        <el-alert
          v-if="session.error"
          :title="session.error"
          type="error"
          :closable="false"
        />
        <p class="help">
          忘记密码时可使用已验证的管理员恢复连接，或由有服务器权限的维护者执行重置工具。
        </p>
        <el-button
          text
          :disabled="session.busy"
          @click="
            mode = 'recovery';
            session.error = '';
          "
          >忘记管理密码</el-button
        >
      </template>
    </el-card>
  </div>
</template>
