import { test } from "node:test";
import assert from "node:assert/strict";
import { taskCanSubmit, taskAnswerPayload } from "../src/chat/task-model.js";
import { browserDrafts } from "../src/chat/drafts.js";
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
