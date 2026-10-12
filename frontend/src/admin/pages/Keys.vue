<script setup>
import { ref } from "vue";
import { ElMessageBox, ElMessage } from "element-plus";
import GrantsForm from "../components/GrantsForm.vue";
import { session, api, run, refresh, botName, copy } from "../session.js";
import { date } from "../../shared/format.js";
const dialog = ref(false),
  grantOnly = ref(false),
  client = ref(null),
  name = ref(""),
  scope = ref({ bot_ids: [], default_bot_id: null }),
  issued = ref(null);
function create() {
  client.value = null;
  name.value = "";
  scope.value = { bot_ids: [], default_bot_id: null };
  grantOnly.value = false;
  dialog.value = true;
}
async function grants(row) {
  await run(async () => {
    scope.value = await api(`clients/${row.id}/bots`);
    client.value = row;
    grantOnly.value = true;
    dialog.value = true;
  });
}
async function save() {
  await run(async () => {
    if (grantOnly.value)
      await api(`clients/${client.value.id}/bots`, scope.value);
    else {
      if (!name.value.trim()) throw Error("请填写密钥名称。");
      issued.value = await api("clients", {
        name: name.value.trim(),
        ...scope.value,
      });
    }
    dialog.value = false;
    await refresh();
    ElMessage.success("已保存");
  });
}
async function action(row, kind) {
  try {
    let body = {};
    if (kind === "rename") {
      const r = await ElMessageBox.prompt(
        "修改来源标记，原密钥仍有效。",
        "修改名称",
        {
          inputValue: row.name,
          confirmButtonText: "保存",
          cancelButtonText: "取消",
        },
      );
      body = { name: r.value.trim() };
    } else
      await ElMessageBox.confirm(
        {
          rotate: "旧密钥立即失效，生成新密钥后需要重新配置调用方。",
          revoke: "停用后此密钥无法调用服务，其他密钥不受影响。",
          delete:
            "永久删除此密钥及调用方身份。历史消息保留，但此操作无法撤销。",
        }[kind],
        row.name,
        {
          confirmButtonText: "确认",
          cancelButtonText: "取消",
          type: "warning",
        },
      );
    await run(async () => {
      const r = await api(`clients/${row.id}/${kind}`, body);
      if (r.api_key) issued.value = r;
      await refresh();
    });
  } catch {}
}
function close(done) {
  if (!session.busy) done();
}
</script>
<template>
  <el-card shadow="never"
    ><div class="section-toolbar">
      <div>
        <h2>接入密钥</h2>
        <p class="help">每个程序或 AI 使用独立密钥，仅能调用获得授权的 Bot。</p>
      </div>
      <el-button type="primary" @click="create">新增密钥</el-button>
    </div>
    <el-table :data="session.clients" stripe empty-text="尚未创建接入密钥"
      ><el-table-column
        prop="name"
        label="调用方名称"
        min-width="150"
      /><el-table-column label="状态" width="100"
        ><template #default="{ row }"
          ><el-tag :type="row.enabled ? 'success' : 'info'">{{
            row.enabled ? "已启用" : "已停用"
          }}</el-tag></template
        ></el-table-column
      ><el-table-column label="授权 Bot" min-width="180"
        ><template #default="{ row }">{{
          (row.bot_ids || []).map(botName).join("、") || "未授权"
        }}</template></el-table-column
      ><el-table-column label="最近调用" min-width="160"
        ><template #default="{ row }">{{
          date(row.last_seen_at, "尚未调用")
        }}</template></el-table-column
      ><el-table-column label="操作" min-width="340"
        ><template #default="{ row }"
          ><el-button
            link
            type="primary"
            :disabled="session.busy"
            @click="grants(row)"
            >Bot 权限</el-button
          ><el-button
            link
            :disabled="session.busy"
            @click="action(row, 'rename')"
            >改名</el-button
          ><el-button
            link
            :disabled="session.busy"
            @click="action(row, 'rotate')"
            >{{ row.enabled ? "重置密钥" : "重新启用" }}</el-button
          ><el-button
            v-if="row.enabled"
            link
            :disabled="session.busy"
            @click="action(row, 'revoke')"
            >停用</el-button
          ><el-button
            link
            type="danger"
            :disabled="session.busy"
            @click="action(row, 'delete')"
            >删除</el-button
          ></template
        ></el-table-column
      ></el-table
    ></el-card
  >
  <el-dialog
    v-model="dialog"
    :title="grantOnly ? 'Bot 权限 · ' + client?.name : '新增接入密钥'"
    width="560px"
    :before-close="close"
    :close-on-click-modal="false"
    destroy-on-close
    ><el-form v-if="!grantOnly" label-position="top"
      ><el-form-item label="调用方名称" required
        ><el-input
          v-model="name"
          maxlength="32"
          placeholder="例如 codex、开票程序" /></el-form-item></el-form
    ><GrantsForm v-model="scope" />
    <p v-if="grantOnly" class="help">保存后权限立即生效，密钥本身不变。</p>
    <template #footer
      ><el-button :disabled="session.busy" @click="dialog = false"
        >取消</el-button
      ><el-button type="primary" :loading="session.busy" @click="save">{{
        grantOnly ? "保存权限" : "创建密钥"
      }}</el-button></template
    ></el-dialog
  >
  <el-dialog
    :model-value="!!issued"
    title="保存接入凭据"
    width="560px"
    @close="issued = null"
    ><template v-if="issued"
      ><el-alert
        title="请妥善保存新密钥；重置密钥会使旧值失效。"
        type="warning"
        :closable="false" /><el-form label-position="top"
        ><el-form-item label="接入密钥"
          ><el-input :model-value="issued.api_key" readonly
            ><template #append
              ><el-button @click="copy(issued.api_key)"
                >复制</el-button
              ></template
            ></el-input
          ></el-form-item
        ><el-form-item label="接入配置"
          ><el-input
            :model-value="
              JSON.stringify(
                { base_url: issued.base_url, api_key: issued.api_key },
                null,
                2,
              )
            "
            type="textarea"
            :rows="5"
            readonly /></el-form-item></el-form></template
    ><template #footer
      ><el-button type="primary" @click="issued = null"
        >已保存，关闭</el-button
      ></template
    ></el-dialog
  >
</template>
