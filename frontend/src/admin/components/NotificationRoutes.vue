<script setup>
import { ref, onMounted } from "vue";
import { api, session, botName } from "../session.js";
import { date } from "../../shared/format.js";
import { stateLabel } from "../delivery-state.js";
const clientFilter = ref("");
const rows = ref([]),
  loading = ref(false),
  loadError = ref(""),
  selected = ref(null);
const rules = {
  explicit: "显式指定",
  application_default: "应用默认",
  conversation_preference: "会话偏好",
  authorized_urgent: "授权紧急",
  muted: "普通静音",
};
async function load() {
  loading.value = true;
  loadError.value = "";
  try {
    rows.value = (
      await api(
        "notification-routes?" +
          new URLSearchParams({ client_id: clientFilter.value }),
      )
    ).routes;
  } catch (e) {
    session.error = e.message;
    loadError.value = e.message;
  } finally {
    loading.value = false;
  }
}
function go(row) {
  location.hash = "conversations?c=" + encodeURIComponent(row.conversation_id);
}
onMounted(load);
</script>
<template>
  <el-card shadow="never"
    ><div class="section-toolbar">
      <div>
        <h2>通知分流记录</h2>
        <p class="help">
          最近 100
          条策略记录。静音、紧急规则及发送前备用均保留独立记录。平台接收不代表业务执行或手机鸣响。
        </p>
      </div>
      <el-button :loading="loading" @click="load">刷新分流记录</el-button>
    </div>
    <el-select
      v-model="clientFilter"
      placeholder="所有应用"
      aria-label="分流记录应用"
      clearable
      @change="load"
      ><el-option
        v-for="a in session.clients"
        :key="a.id"
        :value="a.id"
        :label="a.name"
    /></el-select>
    <el-skeleton v-if="loading" :rows="3" animated /><el-alert
      v-else-if="loadError"
      :title="loadError"
      type="error"
      :closable="false"
    /><el-empty
      v-else-if="!rows.length"
      description="尚无通知策略或静音记录"
    /><el-table v-else :data="rows"
      ><el-table-column label="应用" min-width="120"
        ><template #default="{ row }">{{
          session.clients.find((c) => c.id === row.client_id)?.name ||
          "已删除应用"
        }}</template></el-table-column
      ><el-table-column label="级别" width="85"
        ><template #default="{ row }">{{
          row.level === "urgent" ? "紧急" : "普通"
        }}</template></el-table-column
      ><el-table-column label="连接" min-width="120"
        ><template #default="{ row }">{{
          botName(row.selected_bot)
        }}</template></el-table-column
      ><el-table-column label="选择依据" min-width="120"
        ><template #default="{ row }"
          >{{ rules[row.rule.split(":")[0]] || row.rule
          }}{{ row.rule.includes("fallback") ? " · 发送前备用" : "" }}</template
        ></el-table-column
      ><el-table-column label="结果" min-width="130"
        ><template #default="{ row }">{{
          stateLabel(row.result.status)
        }}</template></el-table-column
      ><el-table-column label="时间" min-width="140"
        ><template #default="{ row }">{{
          date(row.created_at)
        }}</template></el-table-column
      ><el-table-column fixed="right" width="85"
        ><template #default="{ row }"
          ><el-button link @click="selected = row">详情</el-button></template
        ></el-table-column
      ></el-table
    ><el-dialog
      :model-value="!!selected"
      title="单条通知的投递尝试"
      width="600px"
      @close="selected = null"
      ><template v-if="selected"
        ><p class="help">
          每个连接的发送结果单列，发送前备用不会生成另一份业务任务。
        </p>
        <div
          v-for="(a, index) in selected.attempts"
          :key="index"
          class="summary-row"
        >
          <strong>{{ botName(a.bot_id) }}</strong
          ><span>{{ stateLabel(a.status) }}</span
          ><span v-if="a.platform_request_started === false"
            >未开始平台发送</span
          >
        </div>
        <p class="help">
          失败代码：{{ selected.result.error_code ?? "未记录" }} · 阶段：{{
            selected.result.diagnostics?.phase ||
            selected.result.phase ||
            "未记录"
          }}
        </p>
        <el-button v-if="selected.conversation_id" @click="go(selected)"
          >查看会话</el-button
        ></template
      ></el-dialog
    ></el-card
  >
</template>
