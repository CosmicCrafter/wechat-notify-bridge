<script setup>
import { ref, reactive, computed, watch } from "vue";
import { api, run, session } from "../session.js";
import { ElMessage } from "element-plus";
const props = defineProps({ clientId: String, cid: String });
const emit = defineEmits(["updated"]);
const loaded = ref(false);
const visible = ref(false),
  allowed = ref([]),
  form = reactive({
    default_bot: null,
    urgent_bot: null,
    fallback_bot: null,
    urgent_enabled: false,
    interval_seconds: 60,
    bot_id: null,
  });
const endpoint = computed(() =>
  props.cid
    ? "conversations/" + props.cid + "/notification-preference"
    : "clients/" + props.clientId + "/notification-policy",
);
const bots = computed(() =>
  session.bots.filter((b) => allowed.value.includes(b.id)),
);
async function open() {
  loaded.value = false;
  allowed.value = [];
  visible.value = true;
  await run(async () => {
    const r = await api(endpoint.value);
    allowed.value = r.bot_ids;
    loaded.value = true;
    Object.assign(
      form,
      {
        default_bot: null,
        urgent_bot: null,
        fallback_bot: null,
        urgent_enabled: false,
        interval_seconds: 60,
        bot_id: null,
      },
      props.cid
        ? { bot_id: r.bot_id }
        : r.policy
          ? { ...r.policy, urgent_enabled: !!r.policy.urgent_enabled }
          : {},
    );
  });
}
async function save() {
  await run(async () => {
    const value = props.cid
      ? { bot_id: form.bot_id }
      : {
          default_bot: form.default_bot,
          urgent_bot: form.urgent_bot,
          fallback_bot: form.fallback_bot,
          urgent_enabled: form.urgent_enabled,
          interval_seconds: form.interval_seconds,
        };
    await api(endpoint.value, value);
    visible.value = false;
    emit("updated");
    ElMessage.success("通知策略已保存，后续发送仍按连接授权校验。");
  });
}
watch(
  () => [props.clientId, props.cid],
  () => (visible.value = false),
);
defineExpose({ open });
</script>
<template>
  <el-dialog
    v-model="visible"
    :title="cid ? '会话通知偏好' : '应用通知分流'"
    width="560px"
    :close-on-click-modal="false"
    ><p class="help">
      显式目标保持原选择。未指定目标时，会话偏好覆盖应用默认；授权紧急规则可选择
      B。只能选择此应用已获授权的连接。
    </p>
    <el-alert
      v-if="session.error"
      :title="session.error"
      type="error"
      :closable="false"
    />
    <el-form label-position="top" :disabled="!loaded || session.busy"
      ><el-form-item v-if="cid" label="本会话普通提醒连接"
        ><el-select
          v-model="form.bot_id"
          placeholder="沿用应用默认"
          clearable
          @clear="form.bot_id = null"
          ><el-option
            v-for="b in bots"
            :key="b.id"
            :label="b.name + (b.enabled ? '' : '（停用）')"
            :value="b.id" /></el-select></el-form-item
      ><template v-else
        ><el-form-item label="普通提醒默认连接 A"
          ><el-select
            v-model="form.default_bot"
            clearable
            @clear="form.default_bot = null"
            ><el-option
              v-for="b in bots"
              :key="b.id"
              :label="b.name"
              :value="b.id" /></el-select></el-form-item
        ><el-form-item label="紧急提醒专用飞书 B"
          ><el-select
            v-model="form.urgent_bot"
            clearable
            @clear="form.urgent_bot = null"
            ><el-option
              v-for="b in bots.filter((b) => b.platform === 'feishu')"
              :key="b.id"
              :label="b.name"
              :value="b.id" /></el-select></el-form-item
        ><el-checkbox v-model="form.urgent_enabled"
          >授权此应用使用紧急连接及越过静音</el-checkbox
        ><el-form-item label="紧急事件最小间隔（秒）"
          ><el-input-number
            v-model="form.interval_seconds"
            :min="30"
            :max="86400" /></el-form-item
        ><el-form-item label="仅发送前确认未就绪时的备用连接"
          ><el-select
            v-model="form.fallback_bot"
            clearable
            @clear="form.fallback_bot = null"
            ><el-option
              v-for="b in bots"
              :key="b.id"
              :label="b.name"
              :value="b.id" /></el-select></el-form-item></template></el-form
    ><el-alert
      title="平台发送已开始或结果未知时不会自动换 Bot。准备失败保留原目标，按原请求显式重试。飞书 B 不保证突破手机静音。"
      type="info"
      :closable="false"
    /><template #footer
      ><el-button :disabled="session.busy" @click="visible = false"
        >取消</el-button
      ><el-button
        type="primary"
        :disabled="!loaded"
        :loading="session.busy"
        @click="save"
        >保存策略</el-button
      ></template
    ></el-dialog
  >
</template>
