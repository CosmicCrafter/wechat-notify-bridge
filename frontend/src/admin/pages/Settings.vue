<script setup>
import Proxy from "./Proxy.vue";
import Sessions from "./Sessions.vue";
</script>
<template>
  <el-tabs
    ><el-tab-pane label="代理与节点"><Proxy /></el-tab-pane
    ><el-tab-pane label="手机端登录"><Sessions /></el-tab-pane
  ></el-tabs>
</template>
