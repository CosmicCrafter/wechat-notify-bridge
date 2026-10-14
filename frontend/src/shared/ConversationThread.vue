<script setup>
import { ref, computed, watch, defineAsyncComponent } from "vue";
import {
  ArrowLeft,
  Plus,
  Picture,
  Camera,
  Close,
} from "@element-plus/icons-vue";
import { vSwipe, vLongpress } from "../chat/gestures.js";
import { date, deliveryLabels } from "./format.js";
import Markdown from "./Markdown.vue";
import ConversationImage from "./ConversationImage.vue";
const TaskCard = defineAsyncComponent(() => import("../chat/TaskCard.vue"));
const props = defineProps({
  cid: String,
  conversation: Object,
  messages: { type: Array, default: () => [] },
  reply: { type: String, default: "" },
  images: { type: Array, default: () => [] },
  pending: Object,
  anchor: Number,
  older: Boolean,
  newer: Boolean,
  busy: Boolean,
  loading: Boolean,
  error: String,
  canReply: Boolean,
  mobileBack: Boolean,
  ownerLabel: { type: String, default: "你" },
  request: { type: Function, required: true },
  draftStore: { type: Object, required: true },
});
const emit = defineEmits([
  "update:reply",
  "send",
  "choose-images",
  "remove-image",
  "cancel-pending",
  "older",
  "newer",
  "answered",
  "back",
  "refresh",
  "clear-error",
  "scroll-element",
  "manage",
]);
const attachments = ref(false),
  fileInput = ref(),
  cameraInput = ref(),
  imageUrl = ref("");
const title = computed(() =>
  props.conversation
    ? props.conversation.caller + " · " + props.conversation.name
    : props.cid
      ? props.loading
        ? "正在载入会话…"
        : "会话暂时无法载入"
      : "选择一个会话",
);
const subtitle = computed(() =>
  props.conversation?.lifecycle?.monitor_status === "stopped"
    ? "执行端已确认停止 · 历史保留"
    : props.conversation?.archived
      ? props.canReply
        ? "已归档 · 通信继续"
        : "旧版已停用 · 历史保留"
      : props.conversation && !props.canReply
        ? "当前不可回复 · 历史记录仍可查看"
        : "消息、回复与任务 · 两端共享已记录历史",
);
function label(message) {
  if (message.direction !== "user")
    return props.conversation?.caller || "接入应用";
  return message.source === "admin" ? "管理员" : props.ownerLabel;
}
function send() {
  if (
    !props.busy &&
    props.canReply &&
    (props.reply.trim() || props.images.length)
  )
    emit("send");
}
watch(
  () => props.cid,
  () => {
    attachments.value = false;
    imageUrl.value = "";
  },
);
</script>
<template>
  <section class="conversation-thread" :aria-busy="loading">
    <header class="thread-header">
      <el-button
        v-if="mobileBack && cid"
        class="mobile-back"
        text
        :icon="ArrowLeft"
        aria-label="返回会话列表"
        @click="emit('back')"
      />
      <div v-longpress="() => emit('manage')">
        <h2>{{ title }}</h2>
        <p>{{ subtitle }}</p>
      </div>
      <slot name="actions" />
    </header>
    <div v-if="conversation?.receiver" class="receiver-summary">
      <template v-if="conversation.receiver.mode === 'legacy'"
        ><span>应用级接收 · 同一 Key 下未隔离具体聊天</span></template
      >
      <template v-else
        ><strong>{{
          conversation.receiver.status === "active"
            ? "会话接收权限已验证"
            : conversation.receiver.status === "expired"
              ? "接收绑定已过期"
              : conversation.receiver.status === "revoked"
                ? "接收绑定已撤销"
                : "待接收绑定 · 消息可靠入箱"
        }}</strong
        ><span>具体 AI 聊天身份未验证</span></template
      >
    </div>
    <div v-if="conversation?.lifecycle" class="receiver-summary">
      <span>{{
        {
          not_declared: "外部监控未报告",
          running: "执行端报告运行中",
          stop_requested: "停止请求待确认",
          stop_unconfirmed: "停止请求超时 · 状态未知",
          stopped: "执行端已确认停止",
        }[conversation.lifecycle.monitor_status] || "外部状态未知"
      }}</span
      ><strong v-if="conversation.lifecycle.muted">普通通知静音</strong>
    </div>
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      @close="emit('clear-error')"
    />
    <div v-if="!cid" class="thread-welcome">
      <el-empty description="选择会话，查看消息或处理任务" />
    </div>
    <template v-else>
      <div
        class="message-scroll"
        :ref="(element) => emit('scroll-element', element)"
        v-swipe="{
          edge: true,
          action: (direction) => {
            if (mobileBack && direction === 'right') emit('back');
          },
        }"
      >
        <div
          v-if="loading && !conversation"
          class="thread-loading"
          role="status"
        >
          <p>正在加载会话…</p>
          <el-skeleton :rows="3" animated />
        </div>
        <div v-else-if="!conversation" class="thread-welcome">
          <el-empty description="会话暂时无法载入" /><el-button
            :loading="busy"
            @click="emit('refresh')"
            >重新加载会话</el-button
          >
        </div>
        <template v-else>
          <el-button
            v-if="older"
            class="history-button"
            text
            :loading="busy"
            @click="emit('older')"
            >加载更早的消息</el-button
          >
          <article
            v-for="m in messages"
            :key="m.id"
            :id="'message-' + m.id"
            class="message"
            :class="[m.direction, { focused: m.id === anchor, task: !!m.task }]"
          >
            <div class="message-meta">
              <span>{{ label(m) }}</span
              ><time>{{ date(m.created_at) }}</time>
            </div>
            <TaskCard
              v-if="m.task"
              :task="m.task"
              :readonly="!canReply"
              :request="request"
              :draft-store="draftStore"
              @answered="emit('answered', $event)"
            />
            <div v-if="!m.task || m.attachments?.length" class="message-bubble">
              <Markdown v-if="!m.task" :text="m.text || ''" />
              <ConversationImage
                v-for="a in m.attachments || []"
                :key="a.id"
                :cid="cid"
                :image="a"
                :request="request"
                @preview="imageUrl = $event"
              />
            </div>
            <div
              class="delivery-status"
              :class="{
                failed: [
                  'failed',
                  'not_sent',
                  'api_rejected',
                  'unconfirmed_do_not_retry',
                ].includes(m.status),
              }"
            >
              {{ deliveryLabels[m.status] || "已保存" }}
            </div>
            <p v-if="m.processing?.result" class="processing-result">
              应用报告：{{ m.processing.result }}
            </p>
          </article>
          <el-empty
            v-if="!messages.length"
            :description="
              canReply ? '暂无消息，可以发送第一条消息' : '暂无已记录消息'
            "
            :image-size="70"
          />
          <el-button
            v-if="newer"
            class="history-button"
            text
            :loading="busy"
            @click="emit('newer')"
            >加载更新的消息</el-button
          >
        </template>
      </div>
      <form v-if="conversation" class="composer" @submit.prevent="send">
        <div v-if="images.length" class="image-drafts">
          <div v-for="(item, index) in images" :key="item.id || item.url">
            <ConversationImage
              :cid="cid"
              :image="item"
              :request="request"
              :pending="true"
              @preview="imageUrl = $event"
            />
            <span class="sr-only">待发送图片 {{ index + 1 }}</span>
            <el-button
              circle
              size="small"
              :icon="Close"
              aria-label="移除图片"
              :disabled="busy || !!pending"
              @click="emit('remove-image', item)"
            />
          </div>
        </div>
        <div class="compose-row">
          <el-button
            circle
            :icon="Plus"
            aria-label="添加图片"
            :disabled="!canReply || busy || !!pending"
            @click="attachments = !attachments"
          />
          <el-input
            :model-value="reply"
            type="textarea"
            :autosize="{ minRows: 1, maxRows: 5 }"
            maxlength="20000"
            aria-label="回复当前会话"
            :placeholder="canReply ? '回复当前会话…' : '此会话当前只读'"
            :disabled="!canReply || busy"
            :readonly="!!pending"
            @update:model-value="emit('update:reply', $event)"
            @focus="attachments = false"
            @keydown.ctrl.enter.prevent="send"
            @keydown.meta.enter.prevent="send"
          />
          <el-button
            native-type="submit"
            type="primary"
            :loading="busy"
            :disabled="!canReply || (!reply.trim() && !images.length)"
            >{{ pending ? "重试" : "发送" }}</el-button
          >
        </div>
        <div v-if="attachments" class="attachment-tray">
          <el-button
            :icon="Picture"
            :disabled="busy || !!pending"
            @click="fileInput.click()"
            >图片</el-button
          >
          <el-button
            :icon="Camera"
            :disabled="busy || !!pending"
            @click="cameraInput.click()"
            >拍照</el-button
          ><span class="help">最多 3 张图片</span>
        </div>
        <input
          ref="fileInput"
          type="file"
          accept="image/jpeg,image/png,image/webp"
          multiple
          hidden
          @change="emit('choose-images', $event.target)"
        />
        <input
          ref="cameraInput"
          type="file"
          accept="image/*"
          capture="environment"
          hidden
          @change="emit('choose-images', $event.target)"
        />
        <p class="help">
          {{
            !canReply
              ? "会话已归档、应用已停用或暂无有效接收凭据，历史仍可查看。"
              : pending
                ? "提交结果待确认，重试复用原请求，不重复提交。"
                : "消息保存到当前会话，等待所属应用领取与回复。"
          }}<el-button
            v-if="pending"
            link
            :disabled="busy"
            @click="emit('cancel-pending')"
            >取消重试</el-button
          >
        </p>
      </form>
    </template>
    <el-dialog
      :model-value="!!imageUrl"
      title="图片预览"
      width="800px"
      class="conversation-image-preview"
      @close="imageUrl = ''"
      ><img v-if="imageUrl" class="full-image" :src="imageUrl" alt="图片原览"
    /></el-dialog>
  </section>
</template>
<style src="./conversation-thread.css"></style>
