<script setup>
import { ref, computed, onMounted } from "vue";
import { ElMessage } from "element-plus";
import { api, run, session, clearSession } from "../session.js";
import RecoveryBindings from "../components/RecoveryBindings.vue";
const account = ref(null),
  kind = ref(""),
  old = ref(""),
  value = ref(""),
  confirm = ref("");
const visible = computed({
  get: () => !!kind.value,
  set: (value) => {
    if (!value) kind.value = "";
  },
});
onMounted(() =>
  run(async () => {
    account.value = await api("account");
  }),
);
function open(type) {
  kind.value = type;
  old.value = "";
  value.value = type === "username" ? account.value.username : "";
  confirm.value = "";
}
async function save() {
  await run(async () => {
    if (kind.value === "password" && value.value !== confirm.value)
      throw Error("两次新密码不一致。");
    await api("account/" + kind.value, {
      old_password: old.value,
      [kind.value]: value.value,
    });
    kind.value = "";
    old.value = value.value = confirm.value = "";
    clearSession();
    ElMessage.success("已更新，请重新登录。");
  });
}
</script>
<template>
  <el-card shadow="never" v-if="account"
    ><h2>管理员账号</h2>
    <p class="help">账号变更会使所有管理会话失效；接入应用与手机端登录独立。</p>
    <el-descriptions :column="1"
      ><el-descriptions-item label="用户名">{{
        account.username || "尚未建立账号"
      }}</el-descriptions-item
      ><el-descriptions-item label="原管理 Key">{{
        account.legacy_enabled ? "仍可使用" : "已停用"
      }}</el-descriptions-item></el-descriptions
    >
    <div class="actions">
      <el-button :disabled="!account.configured" @click="open('username')"
        >修改用户名</el-button
      ><el-button
        type="primary"
        :disabled="!account.configured"
        @click="open('password')"
        >修改密码</el-button
      >
    </div></el-card
  >
  <RecoveryBindings
    v-if="account?.configured"
    :account="account"
    @updated="(value) => (account = value)"
  />
  <el-dialog
    v-model="visible"
    :title="kind === 'username' ? '修改用户名' : '修改密码'"
    width="440px"
    :close-on-click-modal="false"
    @closed="old = value = confirm = ''"
  >
    <el-form label-position="top" @submit.prevent="save"
      ><el-form-item label="旧密码"
        ><el-input
          v-model="old"
          type="password"
          show-password
          autocomplete="current-password" /></el-form-item
      ><el-form-item
        :label="kind === 'username' ? '新用户名' : '新密码（15–128 字符）'"
        ><el-input
          v-model="value"
          :type="kind === 'username' ? 'text' : 'password'"
          :autocomplete="
            kind === 'username' ? 'username' : 'new-password'
          " /></el-form-item
      ><el-form-item v-if="kind === 'password'" label="确认新密码"
        ><el-input
          v-model="confirm"
          type="password"
          autocomplete="new-password" /></el-form-item></el-form
    ><template #footer
      ><el-button :disabled="session.busy" @click="kind = ''">取消</el-button
      ><el-button type="primary" :loading="session.busy" @click="save"
        >保存并重新登录</el-button
      ></template
    ></el-dialog
  >
</template>
