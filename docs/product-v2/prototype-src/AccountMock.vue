<script setup>
import { ref, reactive, computed } from "vue";
import { ElMessage } from "element-plus";
import {
  Lock,
  Key,
  Connection,
  Warning,
  CircleCheck,
} from "@element-plus/icons-vue";
const props = defineProps({
  state: { type: Object, required: true },
  connections: { type: Array, default: () => [] },
  mode: { type: String, default: "login" },
});
const emit = defineEmits(["login", "logout"]);
const login = reactive({ name: "", password: "" }),
  loginError = ref(""),
  changeDialog = ref(false),
  changeForm = reactive({ old: "", next: "", repeat: "" }),
  changeError = ref("");
const recoverDialog = ref(false),
  recoverStep = ref(0),
  recoveryScenario = ref("normal"),
  recovery = reactive({ name: "admin", code: "", password: "", repeat: "" }),
  recoveryError = ref(""),
  challenge = ref(null),
  recoveryNote = ref(""),
  serverDialog = ref(false);
const bindDialog = ref(false),
  bind = reactive({ old: "", bot: "", code: "" }),
  bindError = ref(""),
  bindIssued = ref(false),
  bindingScenario = ref("normal");
const bound = computed(() =>
  props.connections.find((c) => c.id === props.state.recovery_bot_id),
);
const choices = computed(() =>
  props.connections.filter((c) => c.enabled && c.state === "ready"),
);
function fillDemo() {
  login.name = "admin";
  login.password = props.state.password;
  loginError.value = "";
}
function doLogin() {
  loginError.value = "";
  if (
    login.name.trim() !== props.state.username ||
    login.password !== props.state.password
  ) {
    loginError.value = "账号或密码不正确。";
    return;
  }
  props.state.authenticated = true;
  login.password = "";
  emit("login");
}
function openChange() {
  Object.assign(changeForm, { old: "", next: "", repeat: "" });
  changeError.value = "";
  changeDialog.value = true;
}
function passwordIssue(password, repeat) {
  if (password.length < 15 || password.length > 128)
    return "请使用 15–128 个字符的新密码，可使用长口令。";
  if (password !== repeat) return "两次输入的新密码不一致。";
  if (password === props.state.password) return "新密码不能与旧密码相同。";
  return "";
}
function changePassword() {
  changeError.value = "";
  if (changeForm.old !== props.state.password) {
    changeError.value = "旧密码不正确，密码没有改变。";
    return;
  }
  const issue = passwordIssue(changeForm.next, changeForm.repeat);
  if (issue) {
    changeError.value = issue;
    return;
  }
  props.state.password = changeForm.next;
  props.state.password_changed = "2026-10-14 10:00（示例）";
  props.state.session_version++;
  props.state.authenticated = false;
  changeDialog.value = false;
  Object.assign(changeForm, { old: "", next: "", repeat: "" });
  ElMessage.success("密码已修改，管理会话失效，请重新登录");
  emit("logout");
}
function openRecovery() {
  Object.assign(recovery, {
    name: login.name || "admin",
    code: "",
    password: "",
    repeat: "",
  });
  recoverStep.value = 0;
  challenge.value = null;
  recoveryNote.value = "";
  recoveryError.value = "";
  recoverDialog.value = true;
}
function requestCode() {
  recoveryError.value = "";
  if (!recovery.name.trim()) {
    recoveryError.value = "请填写管理员账号。";
    return;
  }
  if (Date.now() - (props.state.recovery_last_request || 0) < 60000) {
    recoveryError.value = "发送请求过于频繁，请先使用原验证码或等待冷却。";
    return;
  }
  const boundAvailable =
    bound.value && bound.value.enabled && bound.value.state === "ready";
  const validAccount = recovery.name.trim() === props.state.username;
  props.state.recovery_last_request = Date.now();
  challenge.value = {
    issued: Date.now(),
    used: false,
    validated: false,
    attempts: 0,
    canValidate:
      validAccount &&
      boundAvailable &&
      recoveryScenario.value !== "delivery-fail",
  };
  recoverStep.value = 1;
  recoveryNote.value =
    recoveryScenario.value === "delivery-fail"
      ? "模拟发送未完成。没有改密码；请检查既有恢复通道，必要时走服务器兜底。"
      : recoveryScenario.value === "unknown"
        ? "模拟投递结果未知。若手机收到原验证码可继续核验；不重复发码。"
        : "若账号及其恢复通道可用，验证码将发到此前已验证的管理员账号。";
}
function verifyRecovery() {
  recoveryError.value = "";
  const c = challenge.value;
  if (!c || c.used || !c.canValidate) {
    recoveryError.value = "验证码无效或恢复通道不可用，不能重置密码。";
    return;
  }
  if (recoveryScenario.value === "expired" || Date.now() - c.issued > 300000) {
    c.used = true;
    recoveryError.value = "验证码已过期，请重新发起找回。";
    return;
  }
  if (c.attempts >= 5) {
    recoveryError.value = "尝试次数过多，请重新发起找回。";
    return;
  }
  c.attempts++;
  if (recovery.code !== "246810") {
    recoveryError.value = "验证码不正确，密码没有改变。";
    return;
  }
  c.validated = true;
  recoverStep.value = 2;
}
function resetPassword() {
  recoveryError.value = "";
  const c = challenge.value;
  if (!c?.validated || c.used || Date.now() - c.issued > 300000) {
    recoveryError.value = "恢复核验已失效，请重新开始。";
    return;
  }
  const issue = passwordIssue(recovery.password, recovery.repeat);
  if (issue) {
    recoveryError.value = issue;
    return;
  }
  props.state.password = recovery.password;
  props.state.password_changed = "2026-10-14 10:05（示例）";
  props.state.session_version++;
  props.state.authenticated = false;
  c.used = true;
  recoverDialog.value = false;
  login.name = props.state.username;
  login.password = "";
  Object.assign(recovery, { name: "", code: "", password: "", repeat: "" });
  ElMessage.success("密码已重置，旧管理会话与恢复码失效，请用新密码登录");
  emit("logout");
}
function openBinding() {
  Object.assign(bind, { old: "", bot: "", code: "" });
  bindError.value = "";
  bindIssued.value = false;
  bindingScenario.value = "normal";
  bindDialog.value = true;
}
function sendBinding() {
  bindError.value = "";
  if (bind.old !== props.state.password) {
    bindError.value = "请先验证旧密码。";
    return;
  }
  if (!choices.value.some((c) => c.id === bind.bot)) {
    bindError.value =
      "请选择已配置并启用的连接，接收账号固定为该连接的本人账号。";
    return;
  }
  if (bindingScenario.value === "fail") {
    bindError.value = "模拟验证码发送失败，旧绑定继续保护，不能换绑。";
    return;
  }
  bindIssued.value = true;
  ElMessage.info("模拟验证码仅发到所选连接的既定本人账号：246810");
}
function saveBinding() {
  bindError.value = "";
  if (
    bind.old !== props.state.password ||
    !bindIssued.value ||
    bind.code !== "246810"
  ) {
    bindError.value = "旧密码或新通道验证码不正确，原恢复绑定未改变。";
    return;
  }
  props.state.recovery_bot_id = bind.bot;
  const c = choices.value.find((c) => c.id === bind.bot);
  props.state.recovery_owner =
    "本人 · 已验证的" + (c.platform === "wechat" ? "微信" : "飞书") + "账号";
  props.state.session_version++;
  challenge.value = null;
  bindIssued.value = false;
  bindDialog.value = false;
  Object.assign(bind, { old: "", bot: "", code: "" });
  ElMessage.success("新恢复通道已验证并绑定，旧通道保护已释放");
}
function logout() {
  props.state.authenticated = false;
  emit("logout");
}
</script>
<template>
  <div v-if="mode === 'login'" class="auth-page">
    <div class="auth-brand">
      <span class="brand-mark">↗</span>
      <div>
        <strong>Notify Bridge</strong>
        <p>统一消息中转站</p>
      </div>
    </div>
    <section class="panel auth-card">
      <div class="eyebrow">ADMIN CONSOLE</div>
      <h1>登录管理中心</h1>
      <p class="muted">使用管理员账号和密码。</p>
      <el-form label-position="top" @submit.prevent="doLogin"
        ><el-form-item label="账号"
          ><el-input
            v-model="login.name"
            autocomplete="username"
            placeholder="管理员账号"
            aria-label="管理员账号" /></el-form-item
        ><el-form-item label="密码"
          ><el-input
            v-model="login.password"
            type="password"
            show-password
            autocomplete="off"
            placeholder="管理员密码"
            aria-label="管理员密码" /></el-form-item
        ><el-alert
          v-if="loginError"
          :title="loginError"
          type="error"
          :closable="false"
        /><el-button class="full" type="primary" native-type="submit"
          >登录管理中心</el-button
        ></el-form
      ><el-button link @click="openRecovery">忘记密码</el-button>
      <div class="auth-demo">
        <strong>本地交互原型 · 不连接服务</strong>
        <p>示例账号 admin / NotifyBridgeDemo123!。不要填写真实密码。</p>
        <el-button @click="fillDemo">填入示例账号</el-button>
        <p>改密后的示例值只在页面内存中生效；刷新重置。</p>
      </div>
    </section>
  </div>
  <div v-else class="security-page">
    <div class="security-grid">
      <section class="panel">
        <div class="section-title">
          <div>
            <h2>管理员账号</h2>
            <span>管理站点的身份，与接入应用的 API Key 分开。</span>
          </div>
          <span class="status ready"><i />已登录</span>
        </div>
        <dl class="summary-list">
          <dt>账号</dt>
          <dd>{{ state.username }}</dd>
          <dt>密码最近修改</dt>
          <dd>{{ state.password_changed }}</dd>
        </dl>
        <el-button type="primary" :icon="Key" @click="openChange"
          >修改密码</el-button
        ><el-button @click="logout">退出登录</el-button>
      </section>
      <section class="panel">
        <div class="section-title">
          <div>
            <h2>管理员恢复账号</h2>
            <span>验证码只能发送给预先验证的本人账号。</span>
          </div>
          <el-icon><Connection /></el-icon>
        </div>
        <h3>{{ bound?.name || "尚未绑定恢复通道" }}</h3>
        <p class="muted">
          {{
            bound
              ? state.recovery_owner
              : "先配置通信连接，再用旧密码和新通道验证码确认绑定。"
          }}
        </p>
        <el-tag v-if="bound" type="success" effect="plain"
          >恢复保护 · 不能停用或删除</el-tag
        >
        <p class="help">
          换绑先验证新通道再释放旧通道，不通过改配置绕过本人核验。
        </p>
        <el-button :disabled="!choices.length" @click="openBinding">{{
          bound ? "换绑恢复账号" : "绑定恢复账号"
        }}</el-button>
      </section>
    </div>
    <div class="soft-note">
      <el-icon><Warning /></el-icon>
      <div>
        <strong>恢复通道失效时保留服务器兜底</strong>
        <p>
          Bot
          保护不能保证平台永不掉线。具备受授权的服务器权限时，可用服务器专用工具重置管理凭据，保留消息数据、连接凭据与加密主密钥。
        </p>
        <el-button link type="primary" @click="serverDialog = true"
          >查看服务器重置说明</el-button
        >
      </div>
    </div>
  </div>
  <el-dialog
    v-model="changeDialog"
    title="通过旧密码修改密码"
    width="580px"
    class="flow-dialog"
    :close-on-click-modal="false"
    ><div class="flow-body">
      <el-form label-position="top"
        ><el-form-item label="旧密码"
          ><el-input
            v-model="changeForm.old"
            type="password"
            show-password
            aria-label="旧密码"
            autocomplete="off" /></el-form-item
        ><el-form-item label="新密码"
          ><el-input
            v-model="changeForm.next"
            type="password"
            show-password
            aria-label="新密码"
            autocomplete="off"
            placeholder="15–128 字符，可使用长口令" /></el-form-item
        ><el-form-item label="再次输入新密码"
          ><el-input
            v-model="changeForm.repeat"
            type="password"
            show-password
            aria-label="再次输入新密码"
            autocomplete="off" /></el-form-item
      ></el-form>
      <p class="help">
        成功后旧管理会话失效，需要重新登录；应用 API Key 与消息数据不变。
      </p>
      <el-alert
        v-if="changeError"
        :title="changeError"
        type="error"
        :closable="false"
      />
    </div>
    <template #footer
      ><el-button @click="changeDialog = false">取消</el-button
      ><el-button type="primary" @click="changePassword"
        >确认修改密码</el-button
      ></template
    ></el-dialog
  >
  <el-dialog
    v-model="recoverDialog"
    title="找回管理员密码"
    width="620px"
    class="flow-dialog"
    :close-on-click-modal="false"
    ><el-steps :active="recoverStep" align-center
      ><el-step title="请求验证码" /><el-step title="验证本人" /><el-step
        title="设置新密码"
    /></el-steps>
    <div class="flow-body">
      <div class="auth-review">
        <span>评审工具</span
        ><el-select v-model="recoveryScenario" aria-label="找回密码演示场景"
          ><el-option label="验证码正常" value="normal" /><el-option
            label="模拟发送失败"
            value="delivery-fail" /><el-option
            label="模拟投递未知"
            value="unknown" /><el-option
            label="模拟验证码过期"
            value="expired" /></el-select
        ><small>演示验证码固定为 246810，不会真实发送。</small>
      </div>
      <template v-if="recoverStep === 0"
        ><el-form label-position="top"
          ><el-form-item label="管理员账号"
            ><el-input
              v-model="recovery.name"
              aria-label="找回管理员账号" /></el-form-item
        ></el-form>
        <p class="help">
          使用已绑定且已验证的微信 / 飞书本人账号。此处不能输入新接收人或换绑
          Bot。
        </p></template
      ><template v-else-if="recoverStep === 1"
        ><el-alert
          :title="recoveryNote"
          :type="
            recoveryScenario === 'delivery-fail'
              ? 'error'
              : recoveryScenario === 'unknown'
                ? 'warning'
                : 'info'
          "
          :closable="false"
        /><el-form label-position="top"
          ><el-form-item label="验证码"
            ><el-input
              v-model="recovery.code"
              maxlength="6"
              inputmode="numeric"
              aria-label="找回验证码"
              placeholder="演示为 246810" /></el-form-item
        ></el-form>
        <p class="help">
          验证码短时有效、一次使用、限制尝试与发送频率；成功核验只允许重置密码，不直接进入管理中心。
        </p></template
      ><template v-else
        ><el-form label-position="top"
          ><el-form-item label="新密码"
            ><el-input
              v-model="recovery.password"
              type="password"
              show-password
              aria-label="重置新密码"
              placeholder="15–128 字符" /></el-form-item
          ><el-form-item label="再次输入新密码"
            ><el-input
              v-model="recovery.repeat"
              type="password"
              show-password
              aria-label="重置再次输入新密码" /></el-form-item
        ></el-form>
        <p class="help">
          重置后旧管理会话及恢复码失效，请正常登录；只通知重置事件，不发送新密码。
        </p></template
      ><el-alert
        v-if="recoveryError"
        :title="recoveryError"
        type="error"
        :closable="false"
      /><el-button link @click="serverDialog = true"
        >收不到验证码？查看服务器兜底</el-button
      >
    </div>
    <template #footer
      ><el-button @click="recoverDialog = false">取消</el-button
      ><el-button v-if="recoverStep === 0" type="primary" @click="requestCode"
        >模拟发送验证码</el-button
      ><el-button
        v-else-if="recoverStep === 1"
        type="primary"
        @click="verifyRecovery"
        >核验验证码</el-button
      ><el-button v-else type="primary" @click="resetPassword"
        >重置密码并返回登录</el-button
      ></template
    ></el-dialog
  >
  <el-dialog
    v-model="bindDialog"
    :title="bound ? '换绑管理员恢复账号' : '绑定管理员恢复账号'"
    width="620px"
    class="flow-dialog"
    :close-on-click-modal="false"
    ><div class="flow-body">
      <el-form label-position="top"
        ><el-form-item label="旧密码"
          ><el-input
            v-model="bind.old"
            type="password"
            show-password
            aria-label="换绑旧密码" /></el-form-item
        ><el-form-item label="新的恢复连接"
          ><el-select
            v-model="bind.bot"
            aria-label="新的恢复连接"
            @change="
              bindIssued = false;
              bind.code = '';
            "
            ><el-option
              v-for="c in choices"
              :key="c.id"
              :value="c.id"
              :label="c.name" /></el-select
        ></el-form-item>
        <p class="help">
          接收人固定为该连接已经配置的本人账号；验证前原恢复绑定保持不变。
        </p>
        <el-button @click="sendBinding">模拟发送绑定验证码</el-button
        ><el-form-item label="新通道验证码"
          ><el-input
            v-model="bind.code"
            maxlength="6"
            aria-label="绑定验证码"
            placeholder="演示为 246810" /></el-form-item></el-form
      ><el-alert
        v-if="bindError"
        :title="bindError"
        type="error"
        :closable="false"
      />
    </div>
    <template #footer
      ><el-button @click="bindDialog = false">取消</el-button
      ><el-button type="primary" @click="saveBinding"
        >验证并换绑</el-button
      ></template
    ></el-dialog
  >
  <el-dialog
    v-model="serverDialog"
    title="服务器权限下的管理员重置兜底"
    width="680px"
    ><div class="guide-text">
      <p>
        当前稳定服务是管理员 Key
        登录，还没有账号密码重置命令。新版本将增加服务器专用、默认只预览的重置工具，实施前验证具体运行方式。
      </p>
      <ol>
        <li>
          服务器操作者确认身份与重置授权，核对实例、管理员账号、数据目录；先备份管理员状态与配套密钥。
        </li>
        <li>
          在服务器受控终端交互输入新密码，工具只更新管理员密码哈希和会话版本；不打印密码、不通过命令参数传密码。
        </li>
        <li>
          撤销旧管理会话及未使用的恢复码，保留恢复账号、Bot 凭据、API
          Key、消息库和加密主密钥。
        </li>
        <li>
          使用新密码重新登录，核对恢复绑定，再通过安全通道通知本人“管理凭据已重置”，不发送密码。
        </li>
      </ol>
      <p>
        本原型不提供远程重置按钮、不运行重置工具、不连接服务器。若升级需要短时重启或迁移，先在隔离环境验证，再单独安排维护窗口。
      </p>
    </div>
    <template #footer
      ><el-button type="primary" @click="serverDialog = false"
        >关闭</el-button
      ></template
    ></el-dialog
  >
</template>
