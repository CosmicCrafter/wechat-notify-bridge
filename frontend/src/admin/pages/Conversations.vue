<script setup>
import {
  ref,
  computed,
  reactive,
  watch,
  onMounted,
  onBeforeUnmount,
  nextTick,
} from "vue";
import { ElMessageBox, ElMessage } from "element-plus";
import { api, run, session, adminDrafts } from "../session.js";
import ConversationThread from "../../shared/ConversationThread.vue";
import ReceiverPanel from "../components/ReceiverPanel.vue";
import NotificationPolicy from "../components/NotificationPolicy.vue";
import UnassignedReplies from "../components/UnassignedReplies.vue";
import { preparePhoto } from "../../chat/images.js";
import { date } from "../../shared/format.js";
const data = ref(null),
  history = ref(null),
  tasks = ref(null),
  q = ref(""),
  client = ref(""),
  cid = ref(""),
  offset = ref(0),
  anchor = ref(0),
  tab = ref("all"),
  scroll = ref();
const reply = ref(""),
  pending = ref(null),
  attachments = ref([]),
  creating = ref(false),
  newPending = ref(null);
const receiverPanel = ref(),
  notificationPolicy = ref();
const draft = reactive({
  client_id: "",
  name: "",
  text: "",
  receiver_mode: "protected",
});
const previews = reactive(new Map());
const attachmentPreviews = computed(() =>
  attachments.value.map((item) => ({ ...item, url: previews.get(item.id) })),
);
function releasePreview(id) {
  if (previews.has(id)) URL.revokeObjectURL(previews.get(id));
  previews.delete(id);
}
function clearPreviews() {
  for (const id of [...previews.keys()]) releasePreview(id);
}
let generation = 0,
  timer,
  alive = true;
adminDrafts.open(session.account.username);
const saved = adminDrafts.get("new-conversation");
if (saved) {
  Object.assign(draft, saved.draft);
  newPending.value = saved.pending;
  if (newPending.value && !newPending.value.receiver_mode)
    draft.receiver_mode = "legacy";
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
function setScroll(element) {
  scroll.value = element;
}
async function bottom() {
  await nextTick();
  if (scroll.value) scroll.value.scrollTop = scroll.value.scrollHeight;
}
function backToList() {
  persistReply();
  clearPreviews();
  generation++;
  history.value = null;
  cid.value = "";
  reply.value = "";
  pending.value = null;
  attachments.value = [];
  location.hash = "conversations";
}
function cancelPending() {
  pending.value = null;
  persistReply();
  ElMessage.info("已取消重试。先前已到达服务器的消息仍会保留。");
}
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
  clearPreviews();
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
      .querySelector(".conversation-detail .message.focused")
      ?.scrollIntoView({ block: "center" });
  } else if (g === generation) {
    await bottom();
    scroll.value
      ?.closest(".conversation-thread")
      ?.scrollIntoView({ block: "nearest" });
  }
}
async function load() {
  if (tab.value === "unassigned") return;
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
  const target = cid.value,
    g = generation;
  const oldHeight = scroll.value?.scrollHeight || 0,
    oldTop = scroll.value?.scrollTop || 0;
  await run(async () => {
    const result = await readHistory(target, {
      before: history.value.messages[0].id,
    });
    if (g !== generation || !history.value) return;
    history.value.messages = [...result.messages, ...history.value.messages];
    history.value.has_older = result.has_older;
    await nextTick();
    if (scroll.value)
      scroll.value.scrollTop = oldTop + scroll.value.scrollHeight - oldHeight;
  });
}
async function newer() {
  const target = cid.value,
    g = generation;
  const nearBottom =
    scroll.value &&
    scroll.value.scrollHeight -
      scroll.value.scrollTop -
      scroll.value.clientHeight <
      100;
  await run(async () => {
    const result = await readHistory(target, {
      after: history.value.messages.at(-1)?.id || 0,
    });
    if (g !== generation || !history.value) return;
    const map = new Map(history.value.messages.map((m) => [m.id, m]));
    for (const m of result.messages) map.set(m.id, m);
    const ids = [...map.keys()];
    for (let i = 0; i < ids.length; i += 100) {
      const states = await api(
        "conversations/" +
          target +
          "/message-states?ids=" +
          ids.slice(i, i + 100).join(","),
      );
      if (g !== generation || !history.value) return;
      for (const state of states.states)
        Object.assign(map.get(state.id), state);
    }
    history.value.messages = [...map.values()].sort((a, b) => a.id - b.id);
    history.value.has_newer = result.has_newer;
    history.value.conversation = result.conversation;
    if (nearBottom) await bottom();
  });
}
async function fresh() {
  await load();
  if (!alive) return;
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
    Object.assign(draft, {
      client_id: "",
      name: "",
      text: "",
      receiver_mode: "protected",
    });
    adminDrafts.set("new-conversation", null);
    await load();
    await select(result.conversation.id);
    ElMessage.success("首条消息已保存，等待应用领取。");
  }
}
async function sendReply() {
  const target = cid.value,
    g = generation;
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
    if (g !== generation || target !== cid.value) {
      adminDrafts.set("reply:" + target, null);
      return;
    }
    pending.value = null;
    reply.value = "";
    clearPreviews();
    attachments.value = [];
    adminDrafts.set("reply:" + target, null);
    await newer();
    await bottom();
    ElMessage.success("已保存，等待应用领取。");
  }
}
async function upload(input) {
  const files = [...(input.files || [])];
  input.value = "";
  if (
    !files.length ||
    session.busy ||
    pending.value ||
    !history.value?.conversation.can_reply
  )
    return;
  const target = cid.value,
    g = generation;
  await run(async () => {
    if (attachments.value.length + files.length > 3)
      throw Error("每条消息最多 3 张图片。");
    for (const file of files) {
      const photo = await preparePhoto(file);
      let retained = false;
      try {
        if (g !== generation) return;
        const image = await api(
          "conversations/" + target + "/images",
          photo.blob,
        );
        if (g !== generation) return;
        previews.set(image.id, photo.url);
        retained = true;
        attachments.value.push(image);
        persistReply();
      } finally {
        if (!retained) URL.revokeObjectURL(photo.url);
      }
    }
  });
}
function removeImage(id) {
  releasePreview(id);
  attachments.value = attachments.value.filter((a) => a.id !== id);
  persistReply();
}
async function answered(result) {
  if (result.task.conversation_id !== cid.value) return;
  for (const m of history.value?.messages || [])
    if (m.task?.id === result.task.id)
      m.task = { ...result.task, projection: result.projection };
  if (result.projection?.status === "failed")
    ElMessage.warning("答复已保存，平台卡片同步失败；可以再次尝试同步。");
  await load();
  if (history.value) await newer();
}
async function manage(kind) {
  if (kind === "mute") {
    await run(() =>
      api("conversations/" + cid.value + "/mute", {
        muted: !history.value.conversation.lifecycle?.muted,
      }),
    );
    await fresh();
    return;
  }
  if (kind === "stop") {
    try {
      await ElMessageBox.confirm(
        "只向外部执行端发送停止请求，收到确认前不会显示已停止。",
        "请求结束监控",
        { confirmButtonText: "发送停止请求", cancelButtonText: "取消" },
      );
    } catch {
      return;
    }
    await run(() =>
      api("conversations/" + cid.value + "/stop", {
        request_id: crypto.randomUUID(),
      }),
    );
    await fresh();
    return;
  }
  if (kind === "notifications") {
    notificationPolicy.value.open();
    return;
  }
  if (kind === "receiver") {
    receiverPanel.value.open();
    return;
  }
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
        "归档只整理列表，通信与外部监控继续。停止监控需要单独请求并等待执行方确认。",
        "确认会话状态",
        {
          confirmButtonText: chat.archived ? "恢复会话" : "归档",
          cancelButtonText: "取消",
        },
      );
      body = { archived: !chat.archived, visibility_only: true };
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
    if (!session.busy && !document.hidden) fresh();
  }, 10000);
});
onBeforeUnmount(() => {
  alive = false;
  clearPreviews();
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
        ><el-radio-button value="tasks">待处理任务</el-radio-button
        ><el-radio-button value="unassigned"
          >待归属回复</el-radio-button
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
    <UnassignedReplies v-if="tab === 'unassigned'" />
    <div
      v-else
      class="conversation-layout"
      :class="{ 'has-conversation': cid }"
    >
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
              {{
                c.active
                  ? c.archived
                    ? "已归档 · 通信继续"
                    : "可沟通"
                  : "当前不可沟通 · 历史保留"
              }}</small
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
        <ConversationThread
          :cid="cid"
          :conversation="history?.conversation"
          :messages="history?.messages || []"
          v-model:reply="reply"
          :images="attachmentPreviews"
          :pending="pending"
          :anchor="anchor"
          :older="!!history?.has_older"
          :newer="!!history?.has_newer"
          :busy="session.busy"
          :loading="!!cid && !history && session.busy"
          :can-reply="!!history?.conversation.can_reply"
          :mobile-back="true"
          owner-label="本人（手机端）"
          :request="api"
          :draft-store="adminDrafts"
          @scroll-element="setScroll"
          @send="sendReply"
          @choose-images="upload"
          @remove-image="(item) => removeImage(item.id)"
          @cancel-pending="cancelPending"
          @older="older"
          @newer="newer"
          @answered="answered"
          @back="backToList"
          @refresh="select(cid, anchor)"
          @clear-error="session.error = ''"
        >
          <template #actions>
            <el-dropdown v-if="history" @command="manage">
              <el-button :disabled="session.busy">管理会话 ▾</el-button>
              <template #dropdown
                ><el-dropdown-menu>
                  <el-dropdown-item command="pin"
                    >置顶 / 取消置顶</el-dropdown-item
                  >
                  <el-dropdown-item command="rename">修改名称</el-dropdown-item
                  ><el-dropdown-item command="receiver"
                    >接收绑定与权限</el-dropdown-item
                  >
                  <el-dropdown-item command="notifications"
                    >通知偏好</el-dropdown-item
                  >
                  <el-dropdown-item command="archive">{{
                    history.conversation.archived ? "取消归档" : "归档会话"
                  }}</el-dropdown-item>
                  <el-dropdown-item command="mute">{{
                    history.conversation.lifecycle?.muted
                      ? "取消普通通知静音"
                      : "静音普通通知"
                  }}</el-dropdown-item
                  ><el-dropdown-item
                    command="stop"
                    :disabled="!history.conversation.can_reply"
                    >请求结束外部监控</el-dropdown-item
                  ><el-dropdown-item command="delete" divided
                    >永久删除</el-dropdown-item
                  >
                </el-dropdown-menu></template
              >
            </el-dropdown>
          </template>
        </ConversationThread>
      </section>
    </div></el-card
  >
  <NotificationPolicy
    v-if="cid"
    ref="notificationPolicy"
    :cid="cid"
    @updated="fresh"
  />
  <ReceiverPanel v-if="cid" ref="receiverPanel" :cid="cid" @updated="fresh" />
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
      <el-form-item label="接收权限"
        ><el-select
          v-model="draft.receiver_mode"
          :disabled="!!newPending || session.busy"
          ><el-option
            label="受保护会话（需独立接收绑定）"
            value="protected" /><el-option
            label="旧应用级模式（无会话安全隔离）"
            value="legacy" /></el-select
      ></el-form-item>
      <p class="help">
        受保护会话先可靠入箱，验证接收端前不能由共享应用 Key 领取。
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
