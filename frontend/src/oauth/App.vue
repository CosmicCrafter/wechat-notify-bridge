<script setup>
import { ref, onMounted } from "vue";
const requestId = new URL(location.href).searchParams.get("request");
const info = ref(null),
  login = ref(false),
  code = ref(""),
  client = ref(""),
  busy = ref(false),
  error = ref("");
async function api(path, body) {
  const r = await fetch(path, {
    method: body ? "POST" : "GET",
    credentials: "same-origin",
    headers: body
      ? { "Content-Type": "application/json", "X-Chat-Request": "1" }
      : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (r.status === 401) {
    info.value = null;
    login.value = true;
    throw Error("请先登录会话页");
  }
  if (!r.ok)
    throw Error(
      r.status === 410
        ? "授权请求已过期，请回到客户端重新连接。"
        : "请求未完成，请稍后重试。",
    );
  return r.json();
}
async function load() {
  info.value = await api("request?request_id=" + encodeURIComponent(requestId));
  login.value = false;
  client.value = info.value.clients[0]?.id || "";
}
async function run(fn) {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    await fn();
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
async function consent(allow) {
  await run(async () => {
    const r = await api("consent", {
      request_id: requestId,
      api_client: client.value,
      allow,
    });
    location.assign(r.redirect);
  });
}
onMounted(() => run(load));
</script>
<template>
  <main class="login-page">
    <div class="login-brand">↗</div>
    <h1>连接通知桥</h1>
    <el-card class="login-card" shadow="never"
      ><el-alert
        v-if="error"
        :title="error"
        type="warning"
        :closable="false"
      /><el-form
        v-if="login"
        label-position="top"
        @submit.prevent="
          run(async () => {
            await api('../api/login', { code });
            code = '';
            await load();
          })
        "
        ><p class="help">
          输入一次性手机登录码。微信可发送 /web
          获取；纯飞书请管理员在“系统设置→手机端登录”生成，无需绑定微信。
        </p>
        <el-form-item label="8 位登录码"
          ><el-input
            v-model="code"
            inputmode="numeric"
            maxlength="8"
            autocomplete="one-time-code" /></el-form-item
        ><el-button type="primary" native-type="submit" :loading="busy"
          >登录</el-button
        ></el-form
      ><template v-if="info"
        ><h2>{{ info.client_name }} 请求连接</h2>
        <p class="help">
          允许后，可访问所选调用方身份的会话与回复，并使用它获授权的 Bot
          发送通知。
        </p>
        <p class="help">返回地址：{{ new URL(info.redirect_uri).origin }}</p>
        <el-form label-position="top"
          ><el-form-item label="使用哪个调用方身份？"
            ><el-select v-model="client"
              ><el-option
                v-for="c in info.clients"
                :key="c.id"
                :value="c.id"
                :label="c.name" /></el-select></el-form-item
        ></el-form>
        <p class="help">
          停用或删除接入应用会阻止访问。正常轮换 Key 不撤销独立 OAuth
          授权；泄露时需分别撤销相应凭据。
        </p>
        <div class="actions">
          <el-button
            type="primary"
            :disabled="!client"
            :loading="busy"
            @click="consent(true)"
            >允许连接</el-button
          ><el-button :disabled="busy" @click="consent(false)">取消</el-button>
        </div></template
      ><el-link href="../">返回会话页</el-link></el-card
    >
  </main>
</template>
