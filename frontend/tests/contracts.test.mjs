import { test } from "node:test";
import assert from "node:assert/strict";
import { taskCanSubmit, taskAnswerPayload } from "../src/chat/task-model.js";
import { browserDrafts, createDrafts } from "../src/chat/drafts.js";
import { api as phoneRequest, onUnauthorized } from "../src/chat/api.js";
test("leading zero replies and multi-choice limits survive payload conversion", () => {
  const draft = {
    text: "001234",
    choice_ids: [],
    field_values: {},
    choice_id: null,
  };
  assert.deepEqual(taskAnswerPayload({ mode: "input" }, draft), {
    choice_id: null,
    text: "001234",
  });
  assert.equal(
    taskCanSubmit(
      { mode: "multiple", min_choices: 2, max_choices: 3, allow_custom: false },
      { ...draft, choice_ids: ["a"] },
    ),
    false,
  );
  assert.equal(
    taskCanSubmit(
      { mode: "multiple", min_choices: 2, max_choices: 3, allow_custom: false },
      { ...draft, choice_ids: ["a", "b"] },
    ),
    true,
  );
  assert.equal(
    taskCanSubmit(
      { mode: "single", allow_custom: true },
      { ...draft, text: "" },
    ),
    false,
  );
});
test("required form fields and zero values are preserved", () => {
  const task = {
    mode: "form",
    fields: [
      { id: "count", required: true },
      { id: "day", required: false },
    ],
  };
  const draft = { field_values: { count: "0", day: "" } };
  assert.equal(taskCanSubmit(task, draft), true);
  assert.deepEqual(taskAnswerPayload(task, draft), {
    field_values: { count: "0", day: "" },
  });
  assert.equal(taskCanSubmit(task, { field_values: { count: " " } }), false);
});
test("draft storage keeps retry identities and isolates owners", () => {
  const values = new Map();
  globalThis.localStorage = {
    getItem: (k) => values.get(k) || null,
    setItem: (k, v) => values.set(k, v),
    removeItem: (k) => values.delete(k),
  };
  browserDrafts.open("owner-one");
  browserDrafts.set("reply:one", {
    text: "001234",
    pending: { request_id: "stable-retry", attachment_ids: ["image-one"] },
  });
  browserDrafts.open("owner-two");
  assert.equal(browserDrafts.get("reply:one"), undefined);
  browserDrafts.open("owner-one");
  assert.equal(
    browserDrafts.get("reply:one").pending.request_id,
    "stable-retry",
  );
  browserDrafts.clear();
  assert.equal(values.has("wechat-drafts-v1:owner-one"), false);
});
test("admin drafts never load or erase the phone draft namespace", () => {
  const values = new Map();
  globalThis.localStorage = {
    getItem: (k) => values.get(k) || null,
    setItem: (k, v) => values.set(k, v),
    removeItem: (k) => values.delete(k),
  };
  browserDrafts.open("same-owner");
  browserDrafts.set("reply:one", { text: "phone-only" });
  const admin = createDrafts("notify-admin-drafts-v1:");
  admin.open("same-owner");
  assert.equal(admin.get("reply:one"), undefined);
  admin.set("reply:one", {
    text: "admin-only",
    pending: { request_id: "stable-admin-retry" },
  });
  admin.clear();
  assert.equal(browserDrafts.get("reply:one").text, "phone-only");
});

test("phone image downloads return a Blob while image uploads still return metadata", async () => {
  const original = globalThis.fetch;
  const image = new Blob([new Uint8Array([1, 2, 3])], { type: "image/png" });
  globalThis.fetch = async (url, request) => {
    assert.equal(
      url,
      "api/conversations/one/images" +
        (request.method === "GET" ? "/image" : ""),
    );
    assert.equal(request.credentials, "same-origin");
    assert.equal(request.headers.Authorization, undefined);
    assert.equal(request.headers["X-Admin-CSRF"], undefined);
    if (request.method === "GET") return new Response(image);
    assert.equal(request.body, image);
    assert.equal(request.headers["X-Chat-Request"], "1");
    return new Response(JSON.stringify({ id: "image" }), {
      headers: { "Content-Type": "application/json" },
    });
  };
  try {
    const downloaded = await phoneRequest(
      "conversations/one/images/image",
      undefined,
      true,
    );
    assert.ok(downloaded instanceof Blob);
    assert.deepEqual(
      [...new Uint8Array(await downloaded.arrayBuffer())],
      [1, 2, 3],
    );
    assert.deepEqual(
      await phoneRequest("conversations/one/images", image, true),
      { id: "image" },
    );
  } finally {
    globalThis.fetch = original;
  }
});

test("unauthorized image requests clear the phone session and retain the HTTP error", async () => {
  const original = globalThis.fetch;
  let cleared = 0;
  onUnauthorized(() => cleared++);
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ detail: "chat_login_required" }), {
      status: 401,
    });
  try {
    await assert.rejects(
      phoneRequest("conversations/one/images/image", undefined, true),
      (e) => e.status === 401,
    );
    assert.equal(cleared, 1);
  } finally {
    globalThis.fetch = original;
    onUnauthorized(() => {});
  }
});
