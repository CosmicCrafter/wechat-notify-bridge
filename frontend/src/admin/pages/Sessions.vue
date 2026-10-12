<script setup>
import { ref, onBeforeUnmount } from "vue";
import { ElMessageBox, ElMessage } from "element-plus";
import { api, run, session, copy } from "../session.js";
const code = ref("");
let timer;
function issue() {
  run(async () => {
    const r = await api("chat/login-code", {});
    code.value = r.code;
    clearTimeout(timer);
    timer = setTimeout(() => (code.value = ""), 600000);
  });
}
async function revoke() {
  try {
    await ElMessageBox.confirm(
      "所有手机会话页将退出登录，聊天记录保留。",
      "退出全部设备",
      {
        confirmButtonText: "确认退出",
        cancelButtonText: "取消",
        type: "warning",
      },
    );
    await run(async () => {
      await api("chat/revoke-sessions", {});
      code.value = "";
      ElMessage.success("已退出全部设备");
    });
  } catch {}
}
onBeforeUnmount(() => {
  clearTimeout(timer);
  code.value = "";
});
</script>
<template>
  <el-card shadow="never"
    ><div class="section-toolbar">
      <div>
        <h2>手机会话页登录</h2>
        <p class="help">
          查看完整消息、回复和任务卡片；与 Bot 扫码绑定相互独立。
        </p>
      </div>
      <el-link href="../chat/" target="_blank">打开会话页 ↗</el-link>
    </div>
    <el-alert
      title="可在微信发送 /web 获取登录码，也可以在这里生成。登录码 10 分钟有效，使用后失效，新码替换旧码。"
      :closable="false"
    />
    <div class="actions">
      <el-button type="primary" :loading="session.busy" @click="issue"
        >生成一次性登录码</el-button
      ><el-button :disabled="session.busy" @click="revoke"
        >退出全部设备</el-button
      >
    </div>
    <el-input v-if="code" :model-value="code" readonly class="login-code"
      ><template #append
        ><el-button @click="copy(code)">复制</el-button></template
      ></el-input
    ></el-card
  ><el-card shadow="never"
    ><h2>微信指令</h2>
    <el-descriptions :column="1" border
      ><el-descriptions-item
        v-for="[cmd, note] in [
          ['/help', '查看指令说明'],
          ['/status', '查看连接、收发和心跳状态'],
          ['/list', '查看调用方列表'],
          ['/chats', '查看会话名称与路由标签'],
          ['/web', '获取会话页登录码'],
          ['/logout', '退出手机会话页登录'],
        ]"
        :key="cmd"
        :label="cmd"
        >{{ note }}</el-descriptions-item
      ></el-descriptions
    >
    <p class="help">
      连续 12
      小时无有效收发才尝试心跳。未指定会话的回复保留在公共收件箱，不会自动唤醒
      AI。
    </p></el-card
  >
</template>
