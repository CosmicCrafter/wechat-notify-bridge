<script setup>
import { ref, reactive, computed, onBeforeUnmount, watch, nextTick } from "vue";
import { ElMessageBox, ElMessage } from "element-plus";
import { api, session, refresh, copy } from "../session.js";
import { date, connectionLabels } from "../../shared/format.js";
import { confirmConnectionChange } from "../connection-impact.js";
const visible = ref(false),
  step = ref(0),
  bot = ref(null),
  name = ref(""),
  platform = ref("wechat"),
  pair = ref(null),
  qr = ref(""),
  code = ref("");
const config = reactive({
  app_id: "",
  app_secret: "",
  owner_open_id: "",
  verification_token: "",
  encrypt_key: "",
  enabled: true,
});
const callback = ref(""),
  lastEvent = ref(null),
  loading = ref(false);
let generation = 0,
  timer = null,
  qrVersion = "";
const savedConfig = ref(null),
  saving = ref(false),
  loaded = ref(false),
  error = ref(""),
  createdHere = ref(false),
  credentialsSaved = ref(false);
const busy = computed(() => saving.value || session.busy);
const dirty = computed(() =>
  step.value === 0
    ? !!name.value.trim() || platform.value !== "wechat"
    : platform.value === "feishu" &&
      loaded.value &&
      savedConfig.value &&
      Object.keys(config).some((k) => config[k] !== savedConfig.value[k]),
);
async function execute(fn) {
  if (busy.value) return false;
  const started = performance.now();
  saving.value = true;
  error.value = "";
  try {
    await fn();
    return true;
  } catch (e) {
    if (!e.stale) error.value = e.message;
    return false;
  } finally {
    // Keep the replacement footer button disabled through the second click.
    await new Promise((resolve) =>
      setTimeout(resolve, Math.max(0, 400 - (performance.now() - started))),
    );
    saving.value = false;
  }
}
const contentTop = ref();
watch(step, async () => {
  await nextTick();
  const body = contentTop.value?.closest(".el-dialog__body");
  if (body) body.scrollTop = 0;
});
const labels = computed(() =>
  platform.value === "feishu"
    ? ["选择平台", "配置连接", "配置回调"]
    : ["选择平台", "扫码连接", "确认状态"],
);
function clearQr() {
  if (qr.value) URL.revokeObjectURL(qr.value);
  qr.value = "";
  qrVersion = "";
}
function reset() {
  savedConfig.value = null;
  error.value = "";
  loaded.value = false;
  credentialsSaved.value = false;
  createdHere.value = false;
  loading.value = false;
  generation++;
  clearInterval(timer);
  clearQr();
  pair.value = null;
  code.value = "";
  for (const k of Object.keys(config)) config[k] = k === "enabled" ? true : "";
  callback.value = "";
  lastEvent.value = null;
}
function closed() {
  reset();
  bot.value = null;
}
async function close(done) {
  if (busy.value) return;
  const unfinished = createdHere.value && !credentialsSaved.value;
  const pairing = platform.value === "wechat" && pair.value?.pairing.active;
  if (dirty.value || unfinished || pairing) {
    try {
      await ElMessageBox.confirm(
        (dirty.value ? "未保存的输入将丢弃。" : "") +
          (unfinished
            ? "连接记录会保留为待配置，无法投递，可从列表继续配置。"
            : "已保存的配置会保留。") +
          (pairing ? "关闭将取消本次扫码绑定。" : ""),
        "关闭配置？",
        {
          confirmButtonText: "确认关闭",
          cancelButtonText: "继续配置",
          type: "warning",
        },
      );
    } catch (e) {
      if (!["cancel", "close"].includes(e)) error.value = e.message;
      return;
    }
  }
  if (
    pairing &&
    !(await execute(async () => {
      await api(`bots/${bot.value.id}/pairing/cancel`, {
        session_id: pair.value.pairing.session_id,
      });
    }))
  )
    return;
  done();
}
async function finish(event) {
  if (busy.value || event?.detail > 1) return;
  if (await execute(refresh)) {
    visible.value = false;
    ElMessage.success("配置已保存；真实收发状态以连接测试为准。");
  }
}
async function poll() {
  if (
    !visible.value ||
    !bot.value ||
    platform.value !== "wechat" ||
    loading.value
  )
    return;
  loading.value = true;
  const gen = generation,
    id = bot.value.id;
  try {
    const p = await api(`bots/${id}/pairing`);
    if (gen !== generation) return;
    pair.value = p;
    loaded.value = true;
    credentialsSaved.value = !!p.service.bound;
    const v = p.pairing.session_id + "/" + p.pairing.qr_version;
    if (!p.pairing.qr_available) clearQr();
    else if (v !== qrVersion) {
      const blob = await api(
        `bots/${id}/pairing/qr?session_id=${encodeURIComponent(p.pairing.session_id)}`,
        undefined,
        true,
      );
      if (gen !== generation) return;
      clearQr();
      qr.value = URL.createObjectURL(blob);
      qrVersion = v;
    }
    if (p.service.bound && !p.pairing.active) step.value = 2;
  } finally {
    if (gen === generation) loading.value = false;
  }
}
async function open(existing = null) {
  if (busy.value) return;
  reset();
  bot.value = existing;
  name.value = existing?.name || "";
  platform.value = existing?.platform || "wechat";
  step.value = existing ? 1 : 0;
  visible.value = true;
  if (existing) await execute(load);
}
async function load() {
  if (platform.value === "feishu") {
    const gen = generation;
    const d = await api(`bots/${bot.value.id}/feishu`);
    if (gen !== generation) return;
    for (const k of Object.keys(config))
      config[k] =
        k === "enabled" ? (d.configured ? !!d.enabled : true) : (d[k] ?? "");
    config.owner_open_id = d.owner_open_id || d.default_owner_open_id || "";
    savedConfig.value = { ...config };
    credentialsSaved.value = !!d.configured;
    loaded.value = true;
    callback.value = d.callback_url || "";
    lastEvent.value = d.last_event_at;
  } else {
    await poll();
    timer = setInterval(() => {
      if (!session.busy)
        poll().catch((e) => {
          if (!e.stale) error.value = e.message;
        });
    }, 3000);
  }
}
async function next() {
  await execute(async () => {
    if (step.value === 0) {
      if (!name.value.trim()) throw Error("请填写连接名称。");
      bot.value = await api("bots", {
        name: name.value.trim(),
        platform: platform.value,
      });
      createdHere.value = true;
      step.value = 1;
      await refresh();
      await load();
      if (platform.value === "wechat") {
        await api(`bots/${bot.value.id}/pairing/start`, { replace: false });
        await poll();
      }
    } else {
      if (!loaded.value) throw Error("请先重新载入配置。");
      for (const k of [
        "app_id",
        "owner_open_id",
        "app_secret",
        "verification_token",
        "encrypt_key",
      ])
        if (!String(config[k]).trim())
          throw Error("请完整填写应用凭据与接收人 Open ID。");
      if (
        credentialsSaved.value &&
        savedConfig.value &&
        Object.keys(config).some((k) => savedConfig.value[k] !== config[k]) &&
        !(await confirmConnectionChange(bot.value, "更新配置", {
          repair: config.enabled,
        }))
      )
        return;
      const password =
        bot.value.last_recovery_protected &&
        savedConfig.value &&
        Object.keys(config).some((k) => savedConfig.value[k] !== config[k])
          ? await currentPassword()
          : undefined;
      if (password === null) return;
      const d = await api(`bots/${bot.value.id}/feishu`, {
        ...config,
        verify_credentials: true,
        ...(password ? { admin_password: password } : {}),
      });
      savedConfig.value = { ...config };
      credentialsSaved.value = true;
      // The save response is authoritative even if refreshing the list subsequently fails.
      step.value = 2;
      callback.value = d.callback_url || "";
      lastEvent.value = d.last_event_at;
      try {
        await refresh();
      } catch (e) {
        error.value = "凭据已保存，但列表刷新失败：" + e.message;
      }
    }
  });
}
async function startPair() {
  let password;
  if (pair.value?.service.bound) {
    try {
      if (
        !(await confirmConnectionChange(bot.value, "重新绑定", {
          repair: true,
        }))
      )
        return;
      if (bot.value.last_recovery_protected) {
        password = await currentPassword();
        if (password === null) return;
      }
    } catch (e) {
      error.value = e.message;
      return;
    }
  }
  await execute(async () => {
    await api(`bots/${bot.value.id}/pairing/start`, {
      replace: !!pair.value?.service.bound,
      ...(password ? { admin_password: password } : {}),
    });
    step.value = 1;
    await poll();
  });
}
async function currentPassword() {
  try {
    const result = await ElMessageBox.prompt(
      "这是最后恢复连接。请输入当前管理密码，修复后重新验证本人恢复用途。",
      "验证管理身份",
      {
        inputType: "password",
        confirmButtonText: "继续修复",
        cancelButtonText: "取消",
      },
    );
    return result.value;
  } catch (e) {
    if (["cancel", "close"].includes(e)) return null;
    throw e;
  }
}
async function verify() {
  await execute(async () => {
    await api(`bots/${bot.value.id}/pairing/verify`, {
      session_id: pair.value.pairing.session_id,
      code: code.value.trim(),
    });
    code.value = "";
    await poll();
  });
}
defineExpose({ open });
onBeforeUnmount(reset);
</script>
<template>
  <el-dialog
    v-model="visible"
    :title="bot ? '配置连接 · ' + name : '新增通信连接'"
    width="640px"
    class="setup-modal"
    :close-on-click-modal="false"
    :before-close="close"
    destroy-on-close
    @closed="closed"
    ><div ref="contentTop"></div>
    <el-steps :active="step" finish-status="success" simple
      ><el-step v-for="label in labels" :key="label" :title="label"
    /></el-steps>
    <el-alert
      v-if="bot"
      :title="
        credentialsSaved
          ? dirty
            ? '原凭据已保存 · 当前修改尚未保存'
            : '凭据已保存 · 真实收发请单独验证'
          : '连接记录已创建 · 待配置，不可投递'
      "
      type="info"
      :closable="false"
    />
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-button v-if="bot && !loaded" :loading="saving" @click="execute(load)"
      >重新载入配置</el-button
    >
    <div class="step-body">
      <template v-if="step === 0"
        ><h3>选择通信平台</h3>
        <p class="help">每个连接独立配置平台账号，创建后不能更换平台。</p>
        <el-radio-group
          v-model="platform"
          :disabled="busy"
          class="platform-options"
          ><el-radio value="wechat" border>微信 ClawBot</el-radio
          ><el-radio value="feishu" border
            >飞书应用机器人</el-radio
          ></el-radio-group
        ><el-form label-position="top" :disabled="busy" @submit.prevent="next"
          ><el-form-item label="连接名称" required
            ><el-input
              v-model="name"
              maxlength="40"
              placeholder="例如 开票助手、个人微信"
          /></el-form-item>
          <p class="help">
            仅用于通知桥内识别，不会修改平台上的机器人名称。
          </p></el-form
        ></template
      >
      <template v-else-if="platform === 'feishu' && step === 1"
        ><h3>连接应用与接收人</h3>
        <p class="help">
          验证 App ID 和 Secret
          后保存，再到飞书开放平台配置回调；此时仍未证明真实收发。
        </p>
        <el-form
          v-if="loaded"
          label-position="top"
          :disabled="busy"
          @submit.prevent="next"
          ><el-form-item label="应用 ID · App ID" required
            ><el-input
              v-model="config.app_id"
              maxlength="100"
              placeholder="cli_…" /></el-form-item
          ><el-form-item label="应用密钥 · App Secret" required
            ><el-input
              v-model="config.app_secret"
              type="password"
              show-password
              maxlength="256"
              autocomplete="off" /></el-form-item
          ><el-form-item label="接收人 Open ID" required
            ><el-input
              v-model="config.owner_open_id"
              maxlength="100"
              placeholder="ou_…"
            />
            <p class="help">
              用户在当前应用下的 Open ID；不同应用不能直接复用。
            </p></el-form-item
          ><el-form-item label="校验令牌 · Verification Token" required
            ><el-input
              v-model="config.verification_token"
              type="password"
              show-password
              maxlength="256" /></el-form-item
          ><el-form-item label="加密密钥 · Encrypt Key" required
            ><el-input
              v-model="config.encrypt_key"
              type="password"
              show-password
              maxlength="256"
            />
            <p class="help">
              从飞书「事件与回调 → 加密策略」获取，必须与后台一致。
            </p></el-form-item
          ><el-switch v-model="config.enabled" active-text="启用消息收发" />
          <p class="help">
            凭据加密保存，仅向已登录的管理员回显。已有绑定的应用与接收人身份不能替换。
          </p></el-form
        ></template
      >
      <template v-else-if="platform === 'feishu'"
        ><h3>事件与卡片回调地址</h3>
        <el-input :model-value="callback" readonly
          ><template #append
            ><el-button @click="copy(callback)">复制</el-button></template
          ></el-input
        >
        <ol class="instructions">
          <li>
            <strong>开通能力与权限</strong>
            <p>启用应用机器人，申请发送消息与接收单聊消息所需权限。</p>
          </li>
          <li>
            <strong>配置事件与回调</strong>
            <p>
              两处均选择“将回调发送至开发者服务器”，填写上方地址。添加消息事件
              <code>im.message.receive_v1</code> 和卡片回调
              <code>card.action.trigger</code>。
            </p>
          </li>
          <li>
            <strong>发布并验证</strong>
            <p>
              保存并发布应用新版本，再发送消息、点击测试卡片，验证实际收发。
            </p>
          </li>
        </ol>
        <el-alert
          :title="
            lastEvent
              ? '最近接收：' + date(lastEvent)
              : '尚无回调记录。保存配置不代表收发已验证。'
          "
          type="info"
          :closable="false"
      /></template>
      <template v-else
        ><el-alert
          :title="
            !credentialsSaved
              ? '等待扫码绑定 · 当前不可投递'
              : connectionLabels[pair?.service.connection_status] ||
                '正在读取连接状态'
          "
          :type="pair?.service.bound ? 'success' : 'info'"
          :closable="false"
        />
        <div class="pair-stage">
          <img
            v-if="qr"
            :src="qr"
            alt="微信绑定二维码"
            width="224"
            height="224"
          />
          <p>{{ pair?.pairing.message || "正在载入…" }}</p>
          <p v-if="pair?.pairing.active" class="help">
            有效期至 {{ date(pair.pairing.expires_at) }}
          </p>
        </div>
        <el-form
          v-if="pair?.pairing.phase === 'need_verifycode'"
          label-position="top"
          @submit.prevent="verify"
          ><el-form-item label="手机微信显示的连接数字"
            ><el-input
              v-model="code"
              inputmode="numeric"
              maxlength="16" /></el-form-item
          ><el-button type="primary" :loading="saving" @click="verify"
            >验证连接</el-button
          ></el-form
        >
        <div class="actions">
          <el-button
            :disabled="busy || pair?.pairing.active"
            type="primary"
            @click="startPair"
            >{{ pair?.service.bound ? "重新绑定" : "生成二维码" }}</el-button
          ><el-button
            v-if="pair?.pairing.active"
            :disabled="busy"
            @click="
              execute(async () => {
                await api(`bots/${bot.id}/pairing/cancel`, {
                  session_id: pair.pairing.session_id,
                });
                await poll();
              })
            "
            >取消本次绑定</el-button
          >
        </div>
        <el-descriptions v-if="pair?.service.bound" :column="1" border
          ><el-descriptions-item label="最近收发">{{
            date(pair.service.last_activity_at)
          }}</el-descriptions-item
          ><el-descriptions-item label="下次空闲心跳">{{
            date(pair.service.next_heartbeat_at, "等待首条消息")
          }}</el-descriptions-item
          ><el-descriptions-item label="最近接收检查">{{
            date(pair.service.last_poll_success_at)
          }}</el-descriptions-item
          ><el-descriptions-item label="累计接收">{{
            pair.service.inbox_count
          }}</el-descriptions-item></el-descriptions
        ><el-alert
          v-if="pair?.service.send_recovery_hint"
          :title="pair.service.send_recovery_hint"
          type="warning"
          :closable="false"
        />
        <p class="help">
          扫码成功后，在手机 ClawBot 中发送一句话，以建立发送上下文。
        </p></template
      >
    </div>
    <template #footer
      ><el-button
        v-if="platform === 'feishu' && step === 2"
        :disabled="busy"
        @click="step = 1"
        >上一步</el-button
      ><el-button
        v-if="step === 0 || (platform === 'feishu' && step === 1)"
        type="primary"
        :loading="saving"
        :disabled="busy || (step === 1 && !loaded)"
        @click="next"
        >{{ step === 0 ? "下一步" : "保存并继续" }}</el-button
      ><el-button
        v-else
        type="primary"
        :disabled="busy || !credentialsSaved"
        @click="finish"
        >完成</el-button
      ></template
    ></el-dialog
  >
</template>
