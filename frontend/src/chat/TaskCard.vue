<script setup>
import { reactive, ref, computed, watch } from "vue";
import Markdown from "../shared/Markdown.vue";
import { api } from "./api.js";
import { browserDrafts } from "./drafts.js";
import { taskCanSubmit, taskAnswerPayload } from "./task-model.js";
import { date, taskLabels } from "../shared/format.js";
const props = defineProps({
  task: { type: Object, required: true },
  readonly: Boolean,
  request: { type: Function, default: api },
  draftStore: { type: Object, default: () => browserDrafts },
});
const emit = defineEmits(["answered"]);
const drafts = props.draftStore;
const saved = drafts.get("task:" + props.task.id);
const draft = reactive(
  saved?.draft?.cid === props.task.conversation_id
    ? saved.draft
    : {
        choice_id: undefined,
        choice_ids: [],
        text: "",
        field_values: {},
        cid: props.task.conversation_id,
      },
);
draft.field_values ??= {};
const pending = ref(saved?.pending || null),
  busy = ref(false),
  error = ref("");
const mode = computed(() => props.task.mode || "single"),
  locked = computed(
    () =>
      busy.value || !!pending.value || !props.task.can_answer || props.readonly,
  ),
  canSubmit = computed(
    () =>
      !busy.value &&
      props.task.can_answer &&
      !props.readonly &&
      (pending.value || taskCanSubmit(props.task, draft)),
  );
const radioChoice = computed({
  get: () =>
    draft.choice_id === null
      ? "custom:" + props.task.id
      : (draft.choice_id ?? ""),
  set: (value) =>
    (draft.choice_id = value === "custom:" + props.task.id ? null : value),
});
function persist() {
  drafts.set("task:" + props.task.id, {
    draft: {
      ...draft,
      choice_ids: [...draft.choice_ids],
      field_values: { ...draft.field_values },
    },
    pending: pending.value,
  });
}
watch(draft, persist, { deep: true });
watch(
  () => props.task.status,
  (s) => {
    if (s !== "pending") {
      pending.value = null;
      drafts.set("task:" + props.task.id, null);
    }
  },
);
async function submit(choice) {
  if (busy.value || props.readonly || !props.task.can_answer) return;
  if (choice !== undefined) draft.choice_id = choice;
  if (!pending.value && !taskCanSubmit(props.task, draft)) return;
  pending.value ??= {
    request_id: crypto.randomUUID(),
    ...taskAnswerPayload(props.task, draft),
  };
  persist();
  busy.value = true;
  error.value = "";
  try {
    const d = await props.request(
      `conversations/${props.task.conversation_id}/tasks/${props.task.id}/answer`,
      pending.value,
    );
    pending.value = null;
    drafts.set("task:" + props.task.id, null);
    emit("answered", d);
  } catch (e) {
    if (e.status >= 400 && e.status < 500) pending.value = null;
    persist();
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
async function project() {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const result = await props.request(
      "conversations/" +
        props.task.conversation_id +
        "/tasks/" +
        props.task.id +
        "/projection",
      {},
    );
    emit("answered", result);
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
</script>
<!-- Shared by owner and admin; transport and draft scope are explicitly injected. -->
<template>
  <el-card class="task-card" shadow="never"
    ><div class="task-heading">
      <el-tag
        size="small"
        :type="task.status === 'pending' ? 'warning' : 'info'"
        >{{ taskLabels[task.status] || task.status }}</el-tag
      ><span>{{
        ["input", "form"].includes(mode) ? "请补充信息" : "请作出选择"
      }}</span>
    </div>
    <h2>{{ task.title }}</h2>
    <Markdown :text="task.prompt" />
    <el-alert
      v-if="task.projection?.status === 'failed'"
      title="答复已保存，平台卡片尚未同步。"
      type="warning"
      :closable="false"
    />
    <el-button
      v-if="task.projection?.status === 'failed' && !readonly"
      :loading="busy"
      @click="project"
      >重试同步卡片</el-button
    >
    <template v-if="task.status !== 'pending'"
      ><div v-if="task.answer" class="task-answer">
        <strong>你的回复</strong>
        <p v-if="task.answer.choice_labels || task.answer.choice_label">
          {{
            task.answer.choice_labels?.join("、") || task.answer.choice_label
          }}
        </p>
        <p v-for="f in task.answer.fields || []" :key="f.id || f.label">
          {{ f.label }}：{{ f.value || "未填写" }}
        </p>
        <p v-if="task.answer.text">{{ task.answer.text }}</p>
      </div>
      <Markdown v-if="task.result" :text="task.result"
    /></template>
    <el-form v-else label-position="top" @submit.prevent="submit()"
      ><template v-if="mode === 'form'"
        ><el-form-item
          v-for="field in task.fields"
          :key="field.id"
          :label="field.label"
          :required="field.required"
          ><el-select
            v-if="field.type === 'select'"
            v-model="draft.field_values[field.id]"
            :disabled="locked"
            clearable
            :placeholder="field.placeholder || '请选择'"
            ><el-option
              v-for="o in field.options"
              :key="o.id"
              :value="o.id"
              :label="o.label" /></el-select
          ><el-date-picker
            v-else-if="field.type === 'date'"
            v-model="draft.field_values[field.id]"
            :disabled="locked"
            value-format="YYYY-MM-DD"
            format="YYYY-MM-DD"
            :editable="false"
            placeholder="选择日期" /><el-input
            v-else
            v-model="draft.field_values[field.id]"
            :disabled="locked"
            :inputmode="field.type === 'number' ? 'decimal' : 'text'"
            :placeholder="field.placeholder"
            maxlength="1000" /></el-form-item
      ></template>
      <template v-else-if="mode === 'confirm'"
        ><div class="confirm-options">
          <el-button
            v-for="o in task.options"
            :key="o.id"
            :type="o.recommended ? 'primary' : 'default'"
            :disabled="
              busy ||
              readonly ||
              !task.can_answer ||
              (!!pending && pending.choice_id !== o.id)
            "
            @click="submit(o.id)"
            >{{ pending?.choice_id === o.id ? "重试：" : ""
            }}{{ o.label }}</el-button
          ><el-button
            v-if="task.allow_custom"
            text
            :disabled="locked"
            @click="draft.choice_id = null"
            >自行回复</el-button
          >
        </div></template
      >
      <el-checkbox-group
        v-else-if="mode === 'multiple'"
        v-model="draft.choice_ids"
        :disabled="locked"
        :max="task.max_choices"
        class="task-options"
        ><el-checkbox v-for="o in task.options" :key="o.id" :value="o.id" border
          ><strong>{{ o.label }}</strong
          ><small>{{ o.description }}</small></el-checkbox
        ></el-checkbox-group
      >
      <el-radio-group
        v-else-if="mode === 'single'"
        v-model="radioChoice"
        :disabled="locked"
        class="task-options"
        ><el-radio v-for="o in task.options" :key="o.id" :value="o.id" border
          ><strong>{{ o.label }} {{ o.recommended ? "· 推荐" : "" }}</strong
          ><small>{{ o.description }}</small></el-radio
        ><el-radio v-if="task.allow_custom" :value="'custom:' + task.id" border
          >自行回复</el-radio
        ></el-radio-group
      >
      <p v-if="mode === 'multiple'" class="help">
        已选 {{ draft.choice_ids.length }} 项 · 需选 {{ task.min_choices }}–{{
          task.max_choices
        }}
        项
      </p>
      <el-form-item
        v-if="
          mode === 'input' ||
          (mode === 'multiple' && task.allow_custom) ||
          (draft.choice_id === null && mode !== 'form')
        "
        :label="mode === 'multiple' ? '补充说明或自行回复' : '你的回复'"
        ><el-input
          v-model="draft.text"
          type="textarea"
          :autosize="{ minRows: 2, maxRows: 5 }"
          :disabled="locked"
          maxlength="2000"
          :placeholder="task.input_hint || '填写回复…'"
      /></el-form-item>
      <el-alert
        v-if="error"
        :title="error"
        type="error"
        :closable="false"
      /><el-alert
        v-if="readonly || !task.can_answer"
        title="对话已归档或停用，此卡片仅供查看。"
        type="info"
        :closable="false"
      /><el-button
        v-if="mode !== 'confirm' || draft.choice_id === null"
        native-type="submit"
        type="primary"
        :disabled="!canSubmit"
        :loading="busy"
        >{{ pending ? "重试提交" : "提交回复" }}</el-button
      >
      <p class="help">有效期至 {{ date(task.expires_at) }}</p>
      <p v-if="drafts.failed" class="help">
        草稿保存失败，请先复制内容。
      </p></el-form
    ></el-card
  >
</template>
