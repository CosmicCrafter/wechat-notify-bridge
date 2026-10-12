<script setup>
import { ref, defineAsyncComponent } from "vue";
import {
  ArrowLeft,
  Plus,
  Picture,
  Camera,
  Close,
  Setting,
} from "@element-plus/icons-vue";
import { useChat } from "./useChat.js";
import { vLongpress, vSwipe } from "./gestures.js";
import { date, deliveryLabels } from "../shared/format.js";
import Markdown from "../shared/Markdown.vue";
const TaskCard = defineAsyncComponent(() => import("./TaskCard.vue"));
const {
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
} = useChat();
const actionChat = ref(null),
  attachments = ref(false),
  fileInput = ref(),
  cameraInput = ref(),
  imageUrl = ref("");
function actions(chat) {
  if (chat && !s.busy) actionChat.value = chat;
}
async function action(kind) {
  const chat = actionChat.value;
  actionChat.value = null;
  await changeChat(chat, kind);
}
</script>
<template>
  <el-config-provider
    ><main v-if="!s.authenticated" class="login-page">
      <div class="login-brand">↗</div>
      <h1>通知桥 · 会话</h1>
      <p>消息、任务与回复，都在这里</p>
      <el-card class="login-card" shadow="never"
        ><h2>登录会话页</h2>
        <p class="help">在微信发送 /web，或请管理员生成一次性登录码。</p>
        <el-form label-position="top" @submit.prevent="login"
          ><el-form-item label="8 位登录码"
            ><el-input
              v-model="loginCode"
              inputmode="numeric"
              maxlength="8"
              autocomplete="one-time-code"
              placeholder="请输入登录码" /></el-form-item
          ><el-button
            class="full"
            type="primary"
            native-type="submit"
            :loading="s.busy"
            >登录</el-button
          ></el-form
        ><el-alert
          v-if="s.error"
          :title="s.error"
          type="error"
          :closable="false"
        /><el-link href="../admin/">进入管理中心</el-link></el-card
      >
    </main>
    <div v-else class="chat-workspace" :class="{ 'has-chat': s.cid }">
      <aside class="conversation-sidebar">
        <header class="conversation-brand">
          <div>
            <h1>我的会话</h1>
            <p>Notify Bridge</p>
          </div>
          <el-link href="../admin/" aria-label="管理中心"
            ><el-icon :size="21"><Setting /></el-icon
          ></el-link>
        </header>
        <div class="conversation-filters">
          <el-input
            v-model="s.search"
            clearable
            placeholder="搜索会话或待办"
            aria-label="搜索会话"
            @input="searchChange"
          /><el-segmented
            v-model="s.tab"
            :options="[
              { label: '对话', value: 'active' },
              { label: '已归档', value: 'archived' },
              { label: '待办 ' + pendingCount, value: 'tasks' },
            ]"
            block
            @change="tabChange"
          />
          <p class="help">长按会话可改名、归档或删除</p>
        </div>
        <div class="conversation-list">
          <template v-if="s.tab !== 'tasks'"
            ><button
              v-for="chat in filtered"
              :key="chat.id"
              type="button"
              class="conversation-item"
              :class="{ selected: s.cid === chat.id }"
              v-longpress="() => actions(chat)"
              v-swipe="{ action: () => actions(chat) }"
              @click="select(chat.id)"
            >
              <div class="conversation-item-title">
                <strong>{{ chat.caller }} · {{ chat.name }}</strong
                ><el-badge v-if="chat.unread" :value="chat.unread" :max="99" />
              </div>
              <p>
                {{
                  drafts.get(chat.id)
                    ? "草稿：" + drafts.get(chat.id)
                    : chat.preview || "暂无消息"
                }}
              </p>
              <div class="conversation-meta">
                <time>{{ date(chat.last_at) }}</time
                ><span
                  >{{ chat.pinned ? "置顶 " : ""
                  }}{{
                    chat.pending_tasks ? chat.pending_tasks + " 项待办" : ""
                  }}</span
                >
              </div></button
            ><el-empty
              v-if="!filtered.length"
              description="没有符合条件的会话"
              :image-size="70" /></template
          ><template v-else
            ><button
              v-for="item in s.taskList"
              :key="item.task.id"
              type="button"
              class="conversation-item"
              @click="select(item.conversation.id, item.message_id)"
            >
              <small
                >{{ item.conversation.caller }} ·
                {{ item.conversation.name }}</small
              >
              <h3>{{ item.task.title }}</h3>
              <p>有效期至 {{ date(item.task.expires_at) }}</p>
              <el-tag size="small" type="warning">等待答复</el-tag></button
            ><el-empty
              v-if="!s.taskList.length"
              description="没有待答复的任务"
              :image-size="70"
            /><el-button
              v-if="s.taskCursor"
              :loading="s.busy"
              @click="act(() => tasks(true))"
              >加载更多</el-button
            ></template
          >
        </div>
        <footer class="conversation-footer">
          <el-button
            text
            :loading="s.busy"
            @click="
              act(async () => {
                await refreshChats();
                if (s.tab === 'tasks') await tasks();
              })
            "
            >刷新</el-button
          ><el-button text :disabled="s.busy" @click="logout"
            >退出登录</el-button
          >
        </footer>
      </aside>
      <section class="thread">
        <header class="thread-header">
          <el-button
            class="mobile-back"
            text
            :icon="ArrowLeft"
            aria-label="返回会话列表"
            @click="back"
          />
          <div v-longpress="() => actions(s.chat)">
            <h2>
              {{
                s.chat
                  ? s.chat.caller + " · " + s.chat.name
                  : s.cid
                    ? "正在载入…"
                    : "选择一个会话"
              }}
            </h2>
            <p>
              {{
                s.chat?.archived
                  ? "已归档 · 仅查看历史"
                  : s.chat?.active
                    ? "回复发送到当前会话"
                    : "通知、回复与任务记录"
              }}
            </p>
          </div>
          <el-button v-if="s.chat" text @click="actions(s.chat)"
            >管理</el-button
          >
        </header>
        <el-alert
          v-if="s.error"
          :title="s.error"
          type="error"
          @close="s.error = ''"
        />
        <div v-if="!s.cid" class="thread-welcome">
          <el-empty description="从左侧选择会话，查看消息或处理任务" />
        </div>
        <template v-else
          ><div
            class="message-scroll"
            ref="scroll"
            v-swipe="{
              edge: true,
              action: (direction) => {
                if (direction === 'right') back();
              },
            }"
          >
            <el-button
              v-if="s.older"
              text
              :loading="s.busy"
              @click="loadPage(true)"
              >加载更早的消息</el-button
            >
            <article
              v-for="m in s.messages"
              :key="m.id"
              :id="'message-' + m.id"
              class="message"
              :class="[
                m.direction,
                { focused: m.id === s.anchor, task: !!m.task },
              ]"
            >
              <div class="message-meta">
                <span>{{ m.direction === "user" ? "你" : s.chat?.caller }}</span
                ><time>{{ date(m.created_at) }}</time>
              </div>
              <TaskCard
                v-if="m.task"
                :task="m.task"
                :readonly="!s.chat?.active"
                @answered="applyTask"
              />
              <div v-else class="message-bubble">
                <Markdown :text="m.text" /><button
                  v-for="a in m.attachments || []"
                  :key="a.id"
                  class="image-button"
                  @click="
                    imageUrl = `api/conversations/${m.conversation_id}/images/${a.id}`
                  "
                >
                  <img
                    :src="`api/conversations/${m.conversation_id}/images/${a.id}`"
                    loading="lazy"
                    alt="图片附件，点击放大"
                  />
                </button>
              </div>
              <div
                class="delivery-status"
                :class="{
                  failed: ['api_rejected', 'unconfirmed_do_not_retry'].includes(
                    m.status,
                  ),
                }"
              >
                {{ deliveryLabels[m.status] || "已保存" }}
              </div>
            </article>
            <el-empty
              v-if="s.chat && !s.messages.length"
              description="暂无消息"
              :image-size="70"
            /><el-button v-if="s.newer" text @click="loadPage(false)"
              >加载更新的消息</el-button
            >
          </div>
          <form class="composer" @submit.prevent="send">
            <div v-if="selectedImages.length" class="image-drafts">
              <div v-for="item in selectedImages" :key="item.url">
                <img :src="item.url" alt="待发送图片" /><el-button
                  circle
                  size="small"
                  :icon="Close"
                  aria-label="移除图片"
                  :disabled="s.busy || !!replyPending"
                  @click="removeImage(item)"
                />
              </div>
            </div>
            <div class="compose-row">
              <el-button
                circle
                :icon="Plus"
                aria-label="添加图片"
                :disabled="!s.chat?.active || s.busy || !!replyPending"
                @click="attachments = !attachments"
              /><el-input
                v-model="s.reply"
                type="textarea"
                :autosize="{ minRows: 1, maxRows: 5 }"
                maxlength="20000"
                aria-label="回复当前会话"
                placeholder="回复当前会话…"
                :disabled="!s.chat?.active"
                :readonly="!!replyPending"
                @input="saveDraft"
                @focus="attachments = false"
                @keydown.ctrl.enter.prevent="send"
                @keydown.meta.enter.prevent="send"
              /><el-button
                native-type="submit"
                type="primary"
                :loading="s.busy"
                :disabled="
                  !s.chat?.active || (!s.reply.trim() && !selectedImages.length)
                "
                >{{ replyPending ? "重试" : "发送" }}</el-button
              >
            </div>
            <div v-if="attachments" class="attachment-tray">
              <el-button :icon="Picture" @click="fileInput.click()"
                >图片</el-button
              ><el-button :icon="Camera" @click="cameraInput.click()"
                >拍照</el-button
              ><span class="help">最多 3 张图片</span>
            </div>
            <input
              ref="fileInput"
              type="file"
              accept="image/jpeg,image/png,image/webp"
              multiple
              hidden
              @change="chooseImages($event.target)"
            /><input
              ref="cameraInput"
              type="file"
              accept="image/*"
              capture="environment"
              hidden
              @change="chooseImages($event.target)"
            />
            <p class="help">
              {{
                !s.chat?.active
                  ? "此会话只读，历史记录仍可查看。"
                  : replyPending
                    ? "提交结果待确认，重试不会重复入箱。"
                    : "回复提交到当前会话，启用唤醒后会通知对应客户端。"
              }}
              <el-button v-if="replyPending" link @click="cancelPending"
                >取消重试</el-button
              >
            </p>
          </form></template
        >
      </section>
    </div>
    <el-drawer
      :model-value="!!actionChat"
      :title="actionChat?.name || '会话操作'"
      direction="btt"
      size="auto"
      class="chat-action-sheet"
      @close="actionChat = null"
      ><div class="sheet-actions">
        <el-button @click="action('pin')">{{
          actionChat?.pinned ? "取消置顶" : "置顶会话"
        }}</el-button
        ><el-button @click="action('rename')">修改名称</el-button
        ><el-button @click="action('archive')">{{
          actionChat?.archived ? "恢复会话" : "归档会话"
        }}</el-button
        ><el-button type="danger" plain @click="action('delete')"
          >删除会话</el-button
        >
      </div></el-drawer
    ><el-dialog
      :model-value="!!imageUrl"
      title="图片预览"
      width="800px"
      class="image-preview"
      @close="imageUrl = ''"
      ><img
        v-if="imageUrl"
        class="full-image"
        :src="imageUrl"
        alt="图片原览" /></el-dialog
  ></el-config-provider>
</template>
