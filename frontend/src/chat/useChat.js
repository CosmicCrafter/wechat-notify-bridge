import {
  reactive,
  ref,
  computed,
  nextTick,
  onMounted,
  onBeforeUnmount,
} from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { api, onUnauthorized } from "./api.js";
import { browserDrafts } from "./drafts.js";
import { preparePhoto } from "./images.js";
export function useChat() {
  const s = reactive({
    authenticated: false,
    busy: false,
    loading: false,
    error: "",
    chats: [],
    cid: null,
    chat: null,
    messages: [],
    older: false,
    newer: false,
    tab: "active",
    search: "",
    reply: "",
    scope: "",
    anchor: 0,
    taskList: [],
    taskCursor: null,
  });
  const loginCode = ref(""),
    scroll = ref(),
    images = reactive(new Map()),
    drafts = reactive(new Map()),
    pending = reactive(new Map());
  let generation = 0,
    timer,
    polling = false,
    searchTimer,
    taskGeneration = 0,
    alive = true;
  const selectedImages = computed(() => images.get(s.cid) || []),
    replyPending = computed(() => pending.get(s.cid));
  const filtered = computed(() =>
    s.chats.filter(
      (c) =>
        !!c.archived === (s.tab === "archived") &&
        `${c.caller} ${c.name}`.toLowerCase().includes(s.search.toLowerCase()),
    ),
  );
  const pendingCount = computed(() =>
    s.chats.reduce((n, c) => n + c.pending_tasks, 0),
  );
  function fail(e) {
    s.error = e.message || "操作未完成，请稍后重试。";
  }
  async function act(fn) {
    if (s.busy) return;
    s.busy = true;
    s.error = "";
    try {
      return await fn();
    } catch (e) {
      fail(e);
      ElMessage.error(s.error);
    } finally {
      s.busy = false;
    }
  }
  function persist(cid) {
    if (!cid) return;
    const text = drafts.get(cid) || "",
      p = pending.get(cid);
    browserDrafts.set("reply:" + cid, text || p ? { text, pending: p } : null);
  }
  function saveDraft() {
    if (s.cid && s.chat?.id === s.cid) {
      drafts.set(s.cid, s.reply);
      persist(s.cid);
    }
  }
  function clearImages(cid) {
    for (const item of images.get(cid) || []) URL.revokeObjectURL(item.url);
    images.delete(cid);
  }
  function unauthorized() {
    generation++;
    s.authenticated = false;
    s.loading = false;
    s.scope = "";
    s.chat = null;
    s.messages = [];
    s.chats = [];
    s.reply = "";
    drafts.clear();
    pending.clear();
    for (const cid of images.keys()) clearImages(cid);
  }
  async function refreshChats() {
    const gen = generation;
    const d = await api("conversations");
    if (!alive || gen !== generation) return;
    browserDrafts.open(d.draft_scope);
    s.chats = d.conversations;
    if (s.scope !== d.draft_scope) {
      s.scope = d.draft_scope;
      drafts.clear();
      pending.clear();
      for (const c of d.conversations) {
        const entry = browserDrafts.get("reply:" + c.id);
        if (entry && typeof entry.text === "string") {
          drafts.set(c.id, entry.text);
          if (entry.pending?.request_id) pending.set(c.id, entry.pending);
        }
      }
    }
  }
  function merge(messages) {
    const map = new Map(s.messages.map((m) => [m.id, m]));
    for (const m of messages) map.set(m.id, m);
    s.messages = [...map.values()].sort((a, b) => a.id - b.id);
  }
  async function read() {
    if (document.hidden || !s.cid || !s.messages.length) return;
    await api(`conversations/${s.cid}/read`, {
      message_id: s.messages.at(-1).id,
    });
  }
  async function bottom() {
    await nextTick();
    if (scroll.value) scroll.value.scrollTop = scroll.value.scrollHeight;
  }
  async function select(cid, anchor = 0, push = true) {
    saveDraft();
    const gen = ++generation;
    s.cid = cid;
    s.loading = true;
    s.anchor = anchor;
    s.chat = null;
    s.messages = [];
    s.error = "";
    s.reply = drafts.get(cid) || "";
    const url = new URL(location.href);
    url.searchParams.set("c", cid);
    if (anchor) url.searchParams.set("m", anchor);
    else url.searchParams.delete("m");
    if (push) history.pushState({ bridgeChat: true }, "", url);
    else history.replaceState(history.state, "", url);
    try {
      const d = await api(
        `conversations/${cid}/messages${anchor ? "?around=" + anchor : ""}`,
      );
      if (gen !== generation || !alive) return;
      s.chat = d.conversation;
      merge(d.messages);
      s.older = d.has_older;
      s.newer = d.has_newer;
      await nextTick();
      if (anchor)
        document
          .getElementById("message-" + anchor)
          ?.scrollIntoView({ block: "center" });
      else await bottom();
      await read();
      await refreshChats();
    } catch (e) {
      if (gen === generation) fail(e);
    } finally {
      if (gen === generation) s.loading = false;
    }
  }
  function list() {
    saveDraft();
    generation++;
    s.cid = null;
    s.loading = false;
    s.chat = null;
    s.messages = [];
    s.reply = "";
    s.error = "";
  }
  function back() {
    if (history.state?.bridgeChat || history.state?.wechatChat) history.back();
    else {
      const u = new URL(location.href);
      u.search = "";
      history.replaceState(null, "", u);
      list();
    }
  }
  function route() {
    const u = new URL(location.href);
    if (u.searchParams.get("c"))
      select(
        u.searchParams.get("c"),
        Number(u.searchParams.get("m")) || 0,
        false,
      );
    else list();
  }
  async function login() {
    await act(async () => {
      await api("login", { code: loginCode.value });
      loginCode.value = "";
      await refreshChats();
      s.authenticated = true;
      route();
    });
  }
  async function logout() {
    await act(async () => {
      await api("logout", {});
      browserDrafts.clear();
      unauthorized();
      s.scope = "";
    });
  }
  async function loadPage(older) {
    await act(async () => {
      const cid = s.cid,
        gen = generation,
        oldHeight = scroll.value?.scrollHeight || 0,
        oldTop = scroll.value?.scrollTop || 0;
      const d = await api(
        `conversations/${cid}/messages?${older ? "before=" + s.messages[0]?.id : "after=" + (s.messages.at(-1)?.id || 0)}`,
      );
      if (gen !== generation) return;
      merge(d.messages);
      if (older) {
        s.older = d.has_older;
        await nextTick();
        if (scroll.value)
          scroll.value.scrollTop =
            oldTop + scroll.value.scrollHeight - oldHeight;
      } else {
        s.newer = d.has_newer;
        await read();
      }
    });
  }
  async function tasks(append = false) {
    const gen = ++taskGeneration;
    const d = await api(
      "tasks?limit=30" +
        (append && s.taskCursor ? "&before=" + s.taskCursor : "") +
        "&q=" +
        encodeURIComponent(s.search),
    );
    if (gen !== taskGeneration || s.tab !== "tasks") return;
    s.taskList = append ? [...s.taskList, ...d.tasks] : d.tasks;
    s.taskCursor = d.next_before;
  }
  function tabChange() {
    taskGeneration++;
    if (s.tab === "tasks") act(() => tasks());
  }
  function searchChange() {
    clearTimeout(searchTimer);
    if (s.tab === "tasks") {
      taskGeneration++;
      searchTimer = setTimeout(() => tasks().catch(fail), 250);
    }
  }
  function applyTask(data) {
    if (data.task.conversation_id !== s.cid) {
      refreshChats().catch(fail);
      return;
    }
    const m = s.messages.find((m) => m.task?.id === data.task.id);
    if (m) m.task = data.task;
    merge([data.message]);
    refreshChats().catch(fail);
    bottom();
  }
  async function poll() {
    if (
      !s.authenticated ||
      s.busy ||
      polling ||
      document.hidden ||
      document.querySelector('.el-overlay:not([style*="display: none"])')
    )
      return;
    polling = true;
    const gen = generation;
    try {
      await refreshChats();
      if (gen !== generation) return;
      if (s.tab === "tasks" && !s.cid && s.taskList.length <= 30) await tasks();
      if (!s.cid || !s.chat) return;
      const cid = s.cid,
        nearBottom =
          scroll.value &&
          scroll.value.scrollHeight -
            scroll.value.scrollTop -
            scroll.value.clientHeight <
            100;
      const ids = s.messages.map((m) => m.id);
      for (let i = 0; i < ids.length; i += 100) {
        const d = await api(
          `conversations/${cid}/message-states?ids=${ids.slice(i, i + 100).join(",")}`,
        );
        if (gen !== generation) return;
        for (const state of d.states) {
          const m = s.messages.find((m) => m.id === state.id);
          if (m) Object.assign(m, state);
        }
      }
      if (s.newer) return;
      const max = s.messages.at(-1)?.id || 0;
      const d = await api(`conversations/${cid}/messages?after=${max}`);
      if (gen !== generation) return;
      const recent = max
        ? await api(`conversations/${cid}/messages?before=${max + 1}`)
        : { messages: [] };
      if (gen !== generation) return;
      merge([...recent.messages, ...d.messages]);
      s.chat = d.conversation;
      s.newer = d.has_newer;
      if (nearBottom) {
        await bottom();
        await read();
      }
    } catch (e) {
      if (s.authenticated && gen === generation) fail(e);
    } finally {
      polling = false;
    }
  }
  async function chooseImages(input) {
    const cid = s.cid,
      gen = generation,
      files = [...input.files];
    input.value = "";
    if (!s.chat?.active || s.busy || pending.has(cid)) return;
    if ((images.get(cid) || []).length + files.length > 3) {
      ElMessage.warning("每条消息最多发送 3 张图片");
      return;
    }
    await act(async () => {
      for (const file of files) {
        const item = await preparePhoto(file);
        if (gen !== generation || !s.authenticated) {
          URL.revokeObjectURL(item.url);
          return;
        }
        images.set(cid, [...(images.get(cid) || []), item]);
      }
    });
  }
  function removeImage(item) {
    if (s.busy || replyPending.value) return;
    URL.revokeObjectURL(item.url);
    images.set(
      s.cid,
      selectedImages.value.filter((i) => i !== item),
    );
  }
  async function send() {
    if (!s.chat?.active || (!s.reply.trim() && !selectedImages.value.length))
      return;
    const cid = s.cid,
      gen = generation;
    saveDraft();
    await act(async () => {
      const p = pending.get(cid) || {
        text: s.reply,
        request_id: crypto.randomUUID(),
        attachment_ids: [],
      };
      pending.set(cid, p);
      persist(cid);
      for (const item of images.get(cid) || []) {
        if (!item.id) {
          const d = await api(`conversations/${cid}/images`, item.blob, true);
          item.id = d.id;
        }
      }
      if (images.has(cid)) p.attachment_ids = images.get(cid).map((i) => i.id);
      persist(cid);
      const d = await api(`conversations/${cid}/messages`, p);
      clearImages(cid);
      pending.delete(cid);
      drafts.delete(cid);
      persist(cid);
      if (gen === generation) {
        s.reply = "";
        merge([d.message]);
        await bottom();
      }
      await refreshChats();
    });
  }
  function cancelPending() {
    pending.delete(s.cid);
    persist(s.cid);
    ElMessage.info("已取消重试。先前已到达服务器的消息仍会保留。");
  }
  async function changeChat(chat, action) {
    let body = {};
    try {
      if (action === "rename") {
        const { value } = await ElMessageBox.prompt(
          "有效会话不能重名，已归档会话可重名。",
          "修改会话名称",
          {
            inputValue: chat.name,
            confirmButtonText: "保存",
            cancelButtonText: "取消",
          },
        );
        body = { name: value.trim() };
      }
      if (action === "delete") {
        await ElMessageBox.confirm(
          "删除此会话及消息，无法恢复。",
          "删除“" + chat.name + "”？",
          {
            type: "warning",
            confirmButtonText: "删除",
            cancelButtonText: "取消",
          },
        );
      }
      if (action === "archive")
        body = { archived: !chat.archived, visibility_only: true };
      if (action === "pin") body = { pinned: !chat.pinned };
      await act(async () => {
        await api(`conversations/${chat.id}/${action}`, body);
        if (action === "delete") {
          drafts.delete(chat.id);
          pending.delete(chat.id);
          persist(chat.id);
          clearImages(chat.id);
          for (const [id, entry] of Object.entries(browserDrafts.entries))
            if (id.startsWith("task:") && entry.value?.draft?.cid === chat.id)
              browserDrafts.set(id, null);
          if (s.cid === chat.id) {
            s.reply = "";
            const u = new URL(location.href);
            u.search = "";
            history.replaceState(null, "", u);
            list();
          }
        }
        await refreshChats();
        if (s.cid === chat.id) await select(chat.id, 0, false);
        if (s.tab === "tasks") await tasks();
        ElMessage.success(
          action === "archive"
            ? chat.archived
              ? "已取消归档，外部监控状态未改变。"
              : "已归档，通信与外部监控继续。"
            : "已保存",
        );
      });
    } catch {}
  }
  function beforeUnload(e) {
    saveDraft();
    if (images.size || browserDrafts.failed) {
      e.preventDefault();
      e.returnValue = "";
    }
  }
  onMounted(async () => {
    onUnauthorized(unauthorized);
    window.addEventListener("popstate", route);
    window.addEventListener("beforeunload", beforeUnload);
    timer = setInterval(poll, 5000);
    try {
      await refreshChats();
      if (!alive) return;
      s.authenticated = true;
      route();
    } catch (e) {
      if (e.status !== 401) fail(e);
    }
  });
  onBeforeUnmount(() => {
    alive = false;
    generation++;
    clearInterval(timer);
    clearTimeout(searchTimer);
    window.removeEventListener("popstate", route);
    window.removeEventListener("beforeunload", beforeUnload);
    for (const cid of images.keys()) clearImages(cid);
    onUnauthorized(() => {});
  });
  return {
    s,
    loginCode,
    scroll,
    filtered,
    pendingCount,
    selectedImages,
    replyPending,
    drafts,
    act,
    login,
    logout,
    refreshChats,
    select,
    back,
    loadPage,
    tasks,
    tabChange,
    searchChange,
    applyTask,
    chooseImages,
    removeImage,
    send,
    cancelPending,
    changeChat,
    saveDraft,
  };
}
