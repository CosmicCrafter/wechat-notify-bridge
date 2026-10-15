<script setup>
import { ref, computed, watch } from "vue";
import { copy } from "../session.js";
import { recoveryCommand } from "../terminal-recovery.js";
const props = defineProps({ initialize: Boolean });
const expanded = ref(props.initialize ? ["terminal"] : []),
  environment = ref("powershell"),
  database = ref(""),
  backup = ref(""),
  username = ref("");
watch(environment, (value) => {
  database.value = value === "compose" ? "/data/wechat.sqlite3" : "";
  backup.value = value === "compose" ? "/data/admin-reset-backups" : "";
});
const command = computed(() =>
  recoveryCommand({
    environment: environment.value,
    database: database.value,
    backup: backup.value,
    username: username.value,
    initialize: props.initialize,
  }),
);
</script>
<template>
  <el-collapse v-model="expanded" class="terminal-recovery">
    <el-collapse-item
      name="terminal"
      :title="initialize ? '首次安装：初始化管理员' : '服务器终端恢复'"
    >
      <p class="help">
        仅限获得该实例维护授权、具有数据库读写及备份目录权限的维护者，在对应服务器的交互终端执行。浏览器只提供命令。
      </p>
      <el-form label-position="top" @submit.prevent>
        <el-form-item label="执行环境"
          ><el-select v-model="environment" aria-label="终端执行环境"
            ><el-option
              label="Windows PowerShell"
              value="powershell" /><el-option
              label="Linux / macOS shell"
              value="shell" /><el-option
              label="仓库 Docker Compose"
              value="compose" /></el-select
        ></el-form-item>
        <p class="help" v-if="environment === 'compose'">
          在 server/ 的 Compose 目录执行。仓库默认挂载 ./.data 到容器
          /data；此处填写容器内路径，备份需落在持久、仅维护者可访问的可写目录。自定义服务名或挂载时按实际配置修改命令。
        </p>
        <p class="help" v-else>
          本机默认目录为用户主目录下的 .notify-bridge/data/wechat.sqlite3；使用
          --directory 时改为该目录下 data/wechat.sqlite3。ASGI 部署按
          WECHAT_DATA/wechat.sqlite3 填写，并使用已安装服务的 Python 环境。
        </p>
        <el-form-item label="数据库绝对路径"
          ><el-input
            v-model="database"
            placeholder="填写当前实例实际数据库路径"
        /></el-form-item>
        <el-form-item label="私有备份目录绝对路径"
          ><el-input
            v-model="backup"
            placeholder="可写、持久且仅维护者可访问的目录"
        /></el-form-item>
        <el-form-item v-if="initialize" label="要建立的管理员用户名"
          ><el-input
            v-model="username"
            maxlength="32"
            placeholder="填写管理员用户名"
        /></el-form-item>
      </el-form>
      <pre class="terminal-command">{{ command }}</pre>
      <el-button @click="copy(command)">{{
        initialize ? "复制初始化命令" : "复制重置命令"
      }}</el-button>
      <p class="help">
        先替换所有 &lt;…&gt;
        占位符。新密码在终端隐蔽输入两次，不放进命令。工具先做一致性备份并检查完整性，只修改管理凭据和管理会话；不重启服务，不改应用
        Key、消息或主加密密钥。生成备份不等于恢复已验证。
      </p>
    </el-collapse-item>
  </el-collapse>
</template>
<style scoped>
.terminal-recovery {
  margin-top: 20px;
  text-align: left;
}
.terminal-command {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  background: #f5f7fb;
  border-radius: 8px;
  padding: 12px;
  font-size: 12px;
  line-height: 1.7;
}
</style>
