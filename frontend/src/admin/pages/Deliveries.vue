<script setup>
import { ref, onMounted } from "vue";
import { api, run, session, botName } from "../session.js";
import { date } from "../../shared/format.js";
import { stateLabel, stateType } from "../delivery-state.js";
const data = ref(null),
  status = ref(""),
  q = ref(""),
  client = ref(""),
  bot = ref(""),
  selected = ref(null),
  offset = ref(0);
function go(row) {
  location.hash =
    "conversations?c=" +
    encodeURIComponent(row.conversation_id) +
    "&m=" +
    (row.message_id || 0);
}
async function load(reset = false) {
  if (reset) offset.value = 0;
  await run(async () => {
    data.value = await api(
      "deliveries?" +
        new URLSearchParams({
          status: status.value,
          q: q.value,
          client_id: client.value,
          bot_id: bot.value,
          offset: offset.value,
        }),
    );
  });
}
onMounted(() => load());
</script>
<template>
  <el-card shadow="never"
    ><form class="filters" @submit.prevent="load(true)">
      <el-input
        v-model="q"
        placeholder="消息 ID、应用名称或去重标识"
        aria-label="查找投递"
        clearable
      /><el-select
        v-model="status"
        placeholder="所有状态"
        clearable
        aria-label="投递状态"
        ><el-option
          v-for="s in [
            'api_accepted',
            'no_error_reported',
            'api_rejected',
            'not_sent',
            'unconfirmed_do_not_retry',
            'attempting',
          ]"
          :key="s"
          :value="s"
          :label="stateLabel(s)" /></el-select
      ><el-select
        v-model="client"
        clearable
        placeholder="所有应用"
        aria-label="投递应用"
        ><el-option
          v-for="a in session.clients"
          :key="a.id"
          :value="a.id"
          :label="a.name" /></el-select
      ><el-select
        v-model="bot"
        clearable
        placeholder="所有连接"
        aria-label="投递连接"
        ><el-option
          v-for="b in session.bots"
          :key="b.id"
          :value="b.id"
          :label="b.name" /></el-select
      ><el-button native-type="submit" :loading="session.busy">查询</el-button>
    </form>
    <el-table
      v-if="data"
      :data="data.deliveries"
      empty-text="没有匹配的投递记录"
      ><el-table-column label="时间" min-width="160"
        ><template #default="{ row }">{{
          date(row.attempted_at)
        }}</template></el-table-column
      ><el-table-column
        prop="caller"
        label="来源应用"
        min-width="120"
      /><el-table-column label="通信连接" min-width="130"
        ><template #default="{ row }">{{
          botName(row.bot_id)
        }}</template></el-table-column
      ><el-table-column label="状态" min-width="210"
        ><template #default="{ row }"
          ><el-tag :type="stateType(row.status)">{{
            stateLabel(row.status)
          }}</el-tag></template
        ></el-table-column
      ><el-table-column label="操作" width="100"
        ><template #default="{ row }"
          ><el-button link type="primary" @click="selected = row"
            >详情</el-button
          ></template
        ></el-table-column
      ></el-table
    ><el-skeleton v-else :rows="4" animated />
    <div v-if="data" class="pagination">
      <span class="help">共 {{ data.total }} 条</span
      ><el-button
        :disabled="offset === 0 || session.busy"
        @click="
          offset -= 30;
          load();
        "
        >上一页</el-button
      ><el-button
        :disabled="offset + 30 >= data.total || session.busy"
        @click="
          offset += 30;
          load();
        "
        >下一页</el-button
      >
    </div></el-card
  ><el-dialog
    :model-value="!!selected"
    title="投递详情"
    width="600px"
    @close="selected = null"
    ><template v-if="selected"
      ><el-tag :type="stateType(selected.status)">{{
        stateLabel(selected.status)
      }}</el-tag
      ><el-descriptions :column="1"
        ><el-descriptions-item label="逻辑消息 ID">{{
          selected.message_id || "历史记录未关联会话消息"
        }}</el-descriptions-item
        ><el-descriptions-item label="去重摘要"
          ><code>{{ selected.key }}</code></el-descriptions-item
        ><el-descriptions-item label="失败代码">{{
          selected.error_code ?? "未记录"
        }}</el-descriptions-item
        ><el-descriptions-item label="发送阶段">{{
          selected.diagnostics?.phase || "历史诊断未记录"
        }}</el-descriptions-item></el-descriptions
      >
      <pre class="diagnostics">{{
        JSON.stringify(selected.diagnostics, null, 2)
      }}</pre>
      <p class="help">手机收件：未确认。中转站仅展示实际平台响应。</p>
      <el-button v-if="selected.conversation_id" @click="go(selected)"
        >定位会话消息</el-button
      ></template
    ></el-dialog
  >
</template>
