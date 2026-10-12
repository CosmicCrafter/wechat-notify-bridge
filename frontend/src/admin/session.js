import { reactive } from "vue";
import { ElMessage } from "element-plus";
import { errors } from "../shared/errors.js";
export const session = reactive({
  key: "",
  authenticated: false,
  busy: false,
  error: "",
  bots: [],
  clients: [],
  status: null,
  epoch: 0,
});
export function logout() {
  session.epoch++;
  session.key = "";
  session.authenticated = false;
  session.bots = [];
  session.clients = [];
  session.status = null;
  session.error = "";
}
export async function api(path, body, binary = false) {
  const epoch = session.epoch;
  const r = await fetch("api/" + path, {
    method: body === undefined ? "GET" : "POST",
    headers: {
      Authorization: "Bearer " + session.key,
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "omit",
    cache: "no-store",
  });
  if (epoch !== session.epoch)
    throw Object.assign(Error("请求已取消"), { stale: true });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    if (r.status === 401) logout();
    throw Error(
      errors[d.detail] ||
        { 401: "管理员密钥不正确或已失效", 404: "记录已变化，请刷新重试" }[
          r.status
        ] ||
        "操作未完成，请稍后重试。",
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
