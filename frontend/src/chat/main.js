import "element-plus/es/components/message/style/css";
import "element-plus/es/components/message-box/style/css";
import { createApp, h } from "vue";
import { ElConfigProvider } from "element-plus";
import zhCn from "element-plus/es/locale/lang/zh-cn";
import App from "./App.vue";
import "../shared/theme.css";
import "./chat.css";
createApp({
  render: () => h(ElConfigProvider, { locale: zhCn }, () => h(App)),
}).mount("#app");
