<script setup>
import { ref, computed } from "vue";
import { Setting } from "@element-plus/icons-vue";
import { useChat } from "./useChat.js";
import { api } from "./api.js";
import { browserDrafts } from "./drafts.js";
import { vLongpress, vSwipe } from "./gestures.js";
import { date } from "../shared/format.js";
import ConversationThread from "../shared/ConversationThread.vue";
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
const actionChat = ref(null);
function setScroll(element) {
  scroll.value = element;
}
function updateReply(text) {
  s.reply = text;
  saveDraft();
}
const canReply = computed(() => s.chat?.can_reply ?? s.chat?.active);
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
      <ConversationThread
        class="thread"
        :cid="s.cid"
        :conversation="s.chat"
        :messages="s.messages"
        :reply="s.reply"
        :images="selectedImages"
        :pending="replyPending"
        :anchor="s.anchor"
        :older="s.older"
        :newer="s.newer"
        :busy="s.busy"
        :loading="s.loading"
        :error="s.error"
        :can-reply="!!canReply"
        :mobile-back="true"
        :request="api"
        :draft-store="browserDrafts"
        @scroll-element="setScroll"
        @update:reply="updateReply"
        @send="send"
        @choose-images="chooseImages"
        @remove-image="removeImage"
        @cancel-pending="cancelPending"
        @older="loadPage(true)"
        @newer="loadPage(false)"
        @answered="applyTask"
        @back="back"
        @refresh="select(s.cid, s.anchor, false)"
        @clear-error="s.error = ''"
        @manage="actions(s.chat)"
      >
        <template #actions
          ><el-button v-if="s.chat" text @click="actions(s.chat)"
            >管理</el-button
          ></template
        >
      </ConversationThread>
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
          actionChat?.archived ? "取消归档" : "归档会话"
        }}</el-button
        ><el-button type="danger" plain @click="action('delete')"
          >删除会话</el-button
        >
      </div></el-drawer
    >
  </el-config-provider>
</template>
