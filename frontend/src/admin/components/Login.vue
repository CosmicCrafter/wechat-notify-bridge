<script setup>
import { ref } from "vue";
import { session, api, run, refresh, loginAccount } from "../session.js";
const username = ref(""),
  password = ref(""),
  key = ref(""),
  mode = ref("password");
async function login() {
  const ok = await run(async () => {
    if (mode.value === "legacy") {
      session.key = key.value.trim();
      key.value = "";
      await refresh();
    } else {
      if (!username.value || !password.value)
        throw Error("请填写用户名和密码。");
      const value = password.value;
      password.value = "";
      if (mode.value === "setup") {
        session.key = key.value.trim();
        key.value = "";
        try {
          await api("auth/setup", {
            username: username.value,
            password: value,
          });
        } finally {
          session.key = "";
        }
      }
      await loginAccount(username.value, value);
    }
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
      <h2>{{ mode === "setup" ? "建立管理员账号" : "登录管理中心" }}</h2>
      <p class="help">
        {{
          mode === "setup"
            ? "使用原管理 Key 初始化账号。原程序 Key 与通信连接保持有效。"
            : "管理消息、应用与通信连接。"
        }}
      </p>
      <el-form label-position="top" @submit.prevent="login">
        <template v-if="mode !== 'legacy'">
          <el-form-item label="用户名"
            ><el-input
              v-model="username"
              autocomplete="username"
              maxlength="32"
          /></el-form-item>
          <el-form-item
            :label="mode === 'setup' ? '新密码（15–128 字符）' : '密码'"
            ><el-input
              v-model="password"
              type="password"
              show-password
              :autocomplete="
                mode === 'setup' ? 'new-password' : 'current-password'
              "
              maxlength="128"
          /></el-form-item>
        </template>
        <el-form-item v-if="mode !== 'password'" label="原管理员 Key"
          ><el-input
            v-model="key"
            type="password"
            show-password
            autocomplete="off"
        /></el-form-item>
        <el-button
          type="primary"
          native-type="submit"
          :loading="session.busy"
          class="full"
          >{{ mode === "setup" ? "建立账号并登录" : "登录" }}</el-button
        >
      </el-form>
      <el-alert
        v-if="session.error"
        :title="session.error"
        type="error"
        :closable="false"
      />
      <div class="actions login-options">
        <el-button
          text
          @click="mode = mode === 'legacy' ? 'password' : 'legacy'"
          >{{
            mode === "legacy" ? "账号密码登录" : "原管理 Key 登录"
          }}</el-button
        >
        <el-button
          v-if="!session.configured"
          text
          @click="mode = mode === 'setup' ? 'password' : 'setup'"
          >{{ mode === "setup" ? "返回登录" : "首次建立账号" }}</el-button
        >
      </div>
      <p class="help">
        忘记密码时可使用已验证的管理员恢复连接，或由有服务器权限的维护者执行重置工具。
      </p>
    </el-card>
  </div>
</template>
