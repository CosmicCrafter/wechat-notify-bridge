import { reactive } from "vue";
import { ElMessage } from "element-plus";
import { errors } from "../shared/errors.js";
import { createDrafts } from "../chat/drafts.js";
export const adminDrafts = createDrafts("notify-admin-drafts-v1:");
export const session = reactive({
  csrf: "",
  account: null,
  configured: false,
  ready: false,
  authenticated: false,
  busy: false,
  error: "",
  bots: [],
  clients: [],
  status: null,
  epoch: 0,
});
export function clearSession() {
  adminDrafts.clear();
  session.epoch++;
  session.csrf = "";
  session.account = null;
  session.authenticated = false;
  session.bots = [];
  session.clients = [];
  session.status = null;
  session.error = "";
}
export async function logout() {
  try {
    await api("auth/logout", {});
  } finally {
    clearSession();
  }
}
export async function restore() {
  try {
    const result = await api("auth/status");
    session.configured = result.configured;
    if (result.authenticated) {
      session.csrf = result.csrf;
      session.account = result;
      await refresh();
      session.authenticated = true;
    }
  } finally {
    session.ready = true;
  }
}
export async function loginAccount(username, password) {
  const result = await api("auth/login", { username, password });
  session.csrf = result.csrf;
  session.account = result;
  session.configured = true;
  session.epoch++;
  await refresh();
  return true;
}
export async function api(path, body, binary = false) {
  const epoch = session.epoch;
  const r = await fetch("api/" + path, {
    method: body === undefined ? "GET" : "POST",
    headers: {
      "X-Admin-Request": "1",
      ...(session.csrf ? { "X-Admin-CSRF": session.csrf } : {}),
      ...(body === undefined
        ? {}
        : {
            "Content-Type":
              body instanceof Blob ? body.type : "application/json",
          }),
    },
    body:
      body === undefined
        ? undefined
        : body instanceof Blob
          ? body
          : JSON.stringify(body),
    credentials: "same-origin",
    cache: "no-store",
  });
  if (epoch !== session.epoch)
    throw Object.assign(Error("请求已取消"), { stale: true });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    if (r.status === 401 && d.detail === "admin_login_required") clearSession();
    const code = typeof d.detail === "string" ? d.detail : d.detail?.code;
    const platformCode =
      code === "feishu_credentials_rejected" &&
      Number.isSafeInteger(d.detail?.platform_code)
        ? "（飞书代码 " + d.detail.platform_code + "）"
        : "";
    throw Object.assign(
      Error(
        (errors[code] && errors[code] + platformCode) ||
          {
            401: "认证信息不正确或已失效",
            404: "记录已变化，请刷新重试",
            429: "尝试过于频繁，请稍后再试",
          }[r.status] ||
          "操作未完成，请稍后重试。",
      ),
      { status: r.status },
    );
  }
  return binary ? r.blob() : r.json();
}
export async function run(fn) {
  if (session.busy) return;
  session.busy = true;
  session.error = "";
  try {
    return await fn();
  } catch (e) {
    if (!e.stale) {
      session.error = e.message;
      ElMessage.error(e.message);
    }
  } finally {
    session.busy = false;
  }
}
export async function refresh() {
  const [b, c, s] = await Promise.all([
    api("bots"),
    api("clients"),
    api("status"),
  ]);
  session.bots = b.bots;
  session.clients = c.clients;
  session.status = s;
}
export const botName = (id) =>
  session.bots.find((b) => b.id === id)?.name || id;
export async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    ElMessage.success("已复制");
  } catch {
    ElMessage.warning("自动复制不可用，请选择文本手动复制。");
  }
}
