import { errors } from "./errors.js";
let unauthorized = () => {};
export function onUnauthorized(fn) {
  unauthorized = fn;
}
export async function api(path, body, raw = false) {
  const r = await fetch("api/" + path, {
    method: body === undefined ? "GET" : "POST",
    credentials: "same-origin",
    cache: "no-store",
    headers:
      body === undefined
        ? {}
        : {
            "Content-Type": raw ? body.type : "application/json",
            "X-Chat-Request": "1",
          },
    body: body === undefined ? undefined : raw ? body : JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    if (r.status === 401 && path !== "login") unauthorized();
    throw Object.assign(
      Error(errors[data.detail] || "操作未完成，请稍后重试。"),
      { status: r.status, code: data.detail },
    );
  }
  return data;
}
