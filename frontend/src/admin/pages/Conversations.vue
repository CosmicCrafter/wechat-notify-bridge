<script setup>
import {
  ref,
  reactive,
  watch,
  onMounted,
  onBeforeUnmount,
  nextTick,
} from "vue";
import { ElMessageBox, ElMessage } from "element-plus";
import { api, run, session, adminDrafts } from "../session.js";
import Markdown from "../../shared/Markdown.vue";
import TaskCard from "../../chat/TaskCard.vue";
import LedgerImage from "../components/LedgerImage.vue";
import { preparePhoto } from "../../chat/images.js";
import { date } from "../../shared/format.js";
import { stateLabel } from "../delivery-state.js";
const data = ref(null),
  history = ref(null),
  tasks = ref(null),
  q = ref(""),
  client = ref(""),
  cid = ref(""),
  offset = ref(0),
  anchor = ref(0),
  tab = ref("all");
const reply = ref(""),
  pending = ref(null),
  attachments = ref([]),
  creating = ref(false),
  newPending = ref(null);
const draft = reactive({ client_id: "", name: "", text: "" });
let generation = 0,
  timer;
adminDrafts.open(session.account?.username || "legacy");
const saved = adminDrafts.get("new-conversation");
if (saved) {
  Object.assign(draft, saved.draft);
  newPending.value = saved.pending;
}
watch(
  draft,
  () =>
    adminDrafts.set("new-conversation", {
      draft: { ...draft },
      pending: newPending.value,
    }),
  { deep: true },
);
function persistReply() {
  if (cid.value)
    adminDrafts.set("reply:" + cid.value, {
      text: reply.value,
      attachments: attachments.value,
      pending: pending.value,
    });
}
watch(reply, persistReply);
async function readHistory(id, params = {}) {
  const result = await api(
    "conversations/" +
      encodeURIComponent(id) +
      "/messages?" +
      new URLSearchParams(params),
  );
  return result;
}
async function select(id, around = 0) {
  if (session.busy) return;
  persistReply();
  cid.value = id;
  history.value = null;
  const g = ++generation;
  const saved = adminDrafts.get("reply:" + id);
  reply.value = saved?.text || "";
  attachments.value = saved?.attachments || [];
  pending.value = saved?.pending || null;
  await run(async () => {
    const result = await readHistory(id, { around });
    if (g === generation) {
      history.value = result;
      anchor.value = around;
    }
  });
  if (around && g === generation) {
    await nextTick();
    document
      .querySelector(".ledger-message.anchored")
      ?.scrollIntoView({ block: "center" });
  }
}
async function load() {
  await run(async () => {
    if (tab.value === "tasks")
      tasks.value = await api("tasks?" + new URLSearchParams({ q: q.value }));
    else
      data.value = await api(
        "conversations?" +
          new URLSearchParams({
            q: q.value,
            client_id: client.value,
            offset: offset.value,
          }),
      );
  });
}
async function older() {
  await run(async () => {
    const result = await readHistory(cid.value, {
      before: history.value.messages[0].id,
    });
    history.value.messages = [...result.messages, ...history.value.messages];
    history.value.has_older = result.has_older;
  });
}
async function newer() {
  await run(async () => {
    const result = await readHistory(cid.value, {
      after: history.value.messages.at(-1)?.id || 0,
    });
    const map = new Map(history.value.messages.map((m) => [m.id, m]));
    for (const m of result.messages) map.set(m.id, m);
    const ids = [...map.keys()];
    for (let i = 0; i < ids.length; i += 100) {
      const states = await api(
        "conversations/" +
          cid.value +
          "/message-states?ids=" +
          ids.slice(i, i + 100).join(","),
      );
      for (const state of states.states)
        Object.assign(map.get(state.id), state);
    }
    history.value.messages = [...map.values()].sort((a, b) => a.id - b.id);
    history.value.has_newer = result.has_newer;
    history.value.conversation = result.conversation;
  });
}
async function fresh() {
  await load();
  if (history.value) await newer();
}
async function create() {
  const result = await run(async () => {
    if (!draft.client_id || !draft.name || !draft.text.trim())
      throw Error("请选择应用并填写会话名称与首条消息。");
    newPending.value ??= { ...draft, request_id: crypto.randomUUID() };
    adminDrafts.set("new-conversation", {
      draft: { ...draft },
      pending: newPending.value,
    });
    try {
      return await api("conversations", newPending.value);
    } catch (e) {
      if (e.status >= 400 && e.status < 500) {
        newPending.value = null;
        adminDrafts.set("new-conversation", {
          draft: { ...draft },
          pending: null,
        });
      }
      throw e;
    }
  });
  if (result) {
    creating.value = false;
    newPending.value = null;
    Object.assign(draft, { client_id: "", name: "", text: "" });
    adminDrafts.set("new-conversation", null);
    await load();
    await select(result.conversation.id);
    ElMessage.success("首条消息已保存，等待应用领取。");
  }
}
async function sendReply() {
  const target = cid.value;
  const result = await run(async () => {
    if (!reply.value.trim() && !attachments.value.length)
      throw Error("请填写消息或添加图片。");
    pending.value ??= {
      text: reply.value,
      attachment_ids: attachments.value.map((a) => a.id),
      request_id: crypto.randomUUID(),
    };
    persistReply();
    try {
      return await api("conversations/" + target + "/messages", pending.value);
    } catch (e) {
      if (e.status >= 400 && e.status < 500) {
        pending.value = null;
        persistReply();
      }
      throw e;
    }
  });
  if (result) {
    pending.value = null;
    reply.value = "";
    attachments.value = [];
    adminDrafts.set("reply:" + target, null);
    await newer();
    ElMessage.success("已保存，等待应用领取。");
  }
}
async function upload(event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;
  const target = cid.value;
  await run(async () => {
    if (attachments.value.length >= 3) throw Error("每条消息最多 3 张图片。");
    const photo = await preparePhoto(file);
    try {
      const image = await api(
        "conversations/" + target + "/images",
        photo.blob,
      );
      if (target === cid.value) {
        attachments.value.push(image);
        persistReply();
      }
    } finally {
      URL.revokeObjectURL(photo.url);
    }
  });
}
function removeImage(id) {
  attachments.value = attachments.value.filter((a) => a.id !== id);
  persistReply();
}
async function answered(result) {
  for (const m of history.value?.messages || [])
    if (m.task?.id === result.task.id)
      m.task = { ...result.task, projection: result.projection };
  if (result.projection?.status === "failed")
    ElMessage.warning("答复已保存，平台卡片同步失败；可以再次尝试同步。");
  await load();
}
async function manage(kind) {
  const chat = history.value.conversation;
  try {
    let body = {};
    if (kind === "rename") {
      const result = await ElMessageBox.prompt(
        "名称会同步到手机端。",
        "修改会话名称",
        {
          inputValue: chat.name,
          confirmButtonText: "保存",
          cancelButtonText: "取消",
        },
      );
      body = { name: result.value };
    } else if (kind === "pin") {
      body = {
        pinned: !data.value?.conversations.find((c) => c.id === cid.value)
          ?.pinned,
      };
    } else if (kind === "archive") {
      await ElMessageBox.confirm(
        "归档状态会同步到手机端；归档后停止新沟通，保留历史。",
        "确认会话状态",
        {
          confirmButtonText: chat.archived ? "恢复会话" : "归档",
          cancelButtonText: "取消",
        },
      );
      body = { archived: !chat.archived };
    } else {
      await ElMessageBox.confirm(
        "将从管理端和手机端删除会话正文、图片与任务，不能撤销。",
        "永久删除会话",
        {
          type: "warning",
          confirmButtonText: "永久删除",
          cancelButtonText: "取消",
        },
      );
    }
    const done = await run(async () => {
      await api("conversations/" + cid.value + "/" + kind, body);
      return true;
    });
    if (done) {
      if (kind === "delete") {
        history.value = null;
        cid.value = "";
      }
      await load();
      if (history.value) await newer();
    }
  } catch (e) {
    if (!["cancel", "close"].includes(e)) session.error = e.message;
  }
}
function fromHash() {
  const p = new URLSearchParams(location.hash.split("?")[1] || "");
  if (p.get("c")) select(p.get("c"), Number(p.get("m") || 0));
}
onMounted(async () => {
  await load();
  fromHash();
  window.addEventListener("hashchange", fromHash);
  timer = setInterval(() => {
    if (history.value && !session.busy && !document.hidden) newer();
  }, 10000);
});
onBeforeUnmount(() => {
  persistReply();
  generation++;
  clearInterval(timer);
  window.removeEventListener("hashchange", fromHash);
});
</script>
<template>
  <el-card shadow="never"
    ><div class="section-toolbar">
      <el-radio-group v-model="tab" @change="load"
        ><el-radio-button value="all">全部会话</el-radio-button
        ><el-radio-button value="tasks"
          >待处理任务</el-radio-button
        ></el-radio-group
      >
      <div class="actions">
        <el-button :disabled="session.busy" @click="fresh">刷新</el-button
        ><el-button
          type="primary"
          :disabled="session.busy"
          @click="creating = true"
          >新建会话</el-button
        >
      </div>
    </div>
    <form
      class="filters"
      @submit.prevent="
        offset = 0;
        load();
      "
    >
      <el-input
        v-model="q"
        aria-label="搜索会话"
        placeholder="会话、应用或会话 ID"
        clearable
      /><el-select
        v-if="tab === 'all'"
        v-model="client"
        clearable
        placeholder="所有应用"
        aria-label="会话所属应用"
        ><el-option
          v-for="a in session.clients"
          :key="a.id"
          :label="a.name"
          :value="a.id" /></el-select
      ><el-button native-type="submit" :loading="session.busy">查询</el-button>
    </form>
    <div class="conversation-layout">
      <div class="conversation-list">
        <template v-if="tab === 'all'"
          ><el-skeleton v-if="!data" :rows="4" animated /><el-empty
            v-else-if="!data.conversations.length"
            description="没有匹配的会话"
          /><button
            v-for="c in data?.conversations || []"
            :key="c.id"
            class="conversation-item"
            :class="{ selected: cid === c.id }"
            :disabled="session.busy"
            @click="select(c.id)"
          >
            <strong>{{ c.pinned ? "置顶 · " : "" }}{{ c.name }}</strong
            ><small
              >{{ c.caller }} ·
              {{ c.active ? "可沟通" : "已归档 / 应用停用" }}</small
            >
            <p>{{ c.last_message?.text?.slice(0, 90) || "暂无已记录消息" }}</p>
          </button>
          <div class="pagination" v-if="data">
            <el-button
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
          </div></template
        ><template v-else
          ><el-empty
            v-if="tasks && !tasks.tasks.length"
            description="没有待处理任务"
          /><button
            v-for="entry in tasks?.tasks || []"
            :key="entry.task.id"
            class="conversation-item"
            @click="select(entry.conversation.id, entry.message_id)"
          >
            <strong>{{ entry.task.title }}</strong
            ><small
              >{{ entry.conversation.caller }} ·
              {{ entry.conversation.name }}</small
            ></button
          ><el-button
            v-if="tasks?.next_before"
            @click="
              run(async () => {
                const more = await api(
                  'tasks?before=' +
                    tasks.next_before +
                    '&q=' +
                    encodeURIComponent(q),
                );
                tasks.tasks.push(...more.tasks);
                tasks.next_before = more.next_before;
              })
            "
            >更多任务</el-button
          ></template
        >
      </div>
      <section class="conversation-detail">
        <el-empty
          v-if="!history"
          :description="cid ? '正在加载会话…' : '选择会话查看完整已记录历史'"
        /><template v-else
          ><div class="section-toolbar">
            <div>
              <h2>{{ history.conversation.name }}</h2>
              <p class="help">
                {{ history.conversation.caller }} · 仅包含中转站已记录的消息
              </p>
            </div>
            <el-dropdown @command="manage"
              ><el-button :disabled="session.busy">管理会话 ▾</el-button
              ><template #dropdown
                ><el-dropdown-menu
                  ><el-dropdown-item command="pin"
                    >置顶 / 取消置顶</el-dropdown-item
                  ><el-dropdown-item command="rename">修改名称</el-dropdown-item
                  ><el-dropdown-item command="archive">{{
                    history.conversation.archived ? "恢复会话" : "归档会话"
                  }}</el-dropdown-item
                  ><el-dropdown-item command="delete" divided
                    >永久删除</el-dropdown-item
                  ></el-dropdown-menu
                ></template
              ></el-dropdown
            >
          </div>
          <el-button
            v-if="history.has_older"
            :loading="session.busy"
            @click="older"
            >加载更早记录</el-button
          >
          <article
            v-for="m in history.messages"
            :key="m.id"
            class="ledger-message"
            :class="{ anchored: anchor === m.id }"
          >
            <div class="message-meta">
              <strong>{{
                m.direction === "assistant"
                  ? history.conversation.caller
                  : m.source === "admin"
                    ? "管理员"
                    : "用户"
              }}</strong
              ><span>{{ date(m.created_at) }} · #{{ m.id }}</span>
            </div>
            <TaskCard
              v-if="m.task"
              :task="m.task"
              :readonly="!history.conversation.can_reply"
              :request="api"
              :draft-store="adminDrafts"
              @answered="answered"
            /><Markdown v-else :text="m.text || ''" /><LedgerImage
              v-for="a in m.attachments || []"
              :key="a.id"
              :cid="cid"
              :image="a"
            />
            <p class="help">{{ stateLabel(m.status) }}</p>
            <p v-if="m.processing?.result" class="help">
              应用报告：{{ m.processing.result }}
            </p>
            <el-alert
              v-if="m.task?.projection?.status === 'failed'"
              title="答复已保存，平台卡片同步失败。"
              type="warning"
              :closable="false"
            />
          </article>
          <el-empty
            v-if="!history.messages.length"
            description="暂无已记录消息" /><el-button
            v-if="history.has_newer"
            @click="newer"
            >加载后续记录</el-button
          >
          <form
            v-if="history.conversation.can_reply"
            class="reply-composer"
            @submit.prevent="sendReply"
          >
            <p class="help">
              消息保存到本会话，等待所属应用通过 HTTP/MCP
              收件；读取数据不等于执行。
            </p>
            <el-input
              v-model="reply"
              type="textarea"
              :rows="3"
              maxlength="20000"
              aria-label="回复当前会话"
              placeholder="继续沟通…"
              :disabled="session.busy || !!pending"
            />
            <div class="actions">
              <label class="upload-button"
                >添加图片<input
                  type="file"
                  accept="image/*"
                  :disabled="session.busy || !!pending"
                  @change="upload" /></label
              ><el-tag
                v-for="a in attachments"
                :key="a.id"
                :closable="!pending && !session.busy"
                @close="removeImage(a.id)"
                >图片 {{ attachments.indexOf(a) + 1 }}</el-tag
              ><el-button
                native-type="submit"
                type="primary"
                :loading="session.busy"
                >{{ pending ? "用原请求重试" : "发送到应用" }}</el-button
              >
            </div>
          </form>
          <el-alert
            v-else
            title="会话已归档、应用已停用或暂无有效接收凭据，仅能查看历史。"
            type="info"
            :closable="false"
        /></template>
      </section></div
  ></el-card>
  <el-dialog
    v-model="creating"
    title="新建会话并发送首条消息"
    width="560px"
    :close-on-click-modal="false"
    ><el-form label-position="top" @submit.prevent="create"
      ><el-form-item label="接入应用" required
        ><el-select
          v-model="draft.client_id"
          aria-label="新会话接入应用"
          :disabled="!!newPending || session.busy"
          ><el-option
            v-for="a in session.clients"
            :key="a.id"
            :value="a.id"
            :label="a.name"
            :disabled="!a.enabled" /></el-select
      ></el-form-item>
      <p class="help">
        接收方式：应用 HTTP/MCP 收件箱。主机是否在线未知；离线时消息等待领取。
      </p>
      <el-form-item label="会话名称" required
        ><el-input
          v-model="draft.name"
          maxlength="20"
          :disabled="!!newPending || session.busy" /></el-form-item
      ><el-form-item label="首条消息" required
        ><el-input
          v-model="draft.text"
          type="textarea"
          :rows="5"
          maxlength="20000"
          :disabled="!!newPending || session.busy" /></el-form-item
      ><el-alert
        v-if="newPending"
        title="上次请求结果尚未确认；重试会复用原请求，不另建会话。"
        type="warning"
        :closable="false" /></el-form
    ><template #footer
      ><el-button :disabled="session.busy" @click="creating = false">{{
        newPending ? "保留草稿，关闭" : "取消"
      }}</el-button
      ><el-button type="primary" :loading="session.busy" @click="create">{{
        newPending ? "确认原请求结果" : "创建并发送"
      }}</el-button></template
    ></el-dialog
  >
</template>
