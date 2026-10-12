<script setup>
import { watch } from "vue";
import { session } from "../session.js";
import { platformName } from "../../shared/format.js";
const model = defineModel({ required: true });
watch(
  () => model.value.bot_ids,
  (ids) => {
    if (!ids.includes(model.value.default_bot_id))
      model.value.default_bot_id = null;
  },
  { deep: true },
);
</script>
<template>
  <el-form label-position="top"
    ><el-form-item label="允许调用的 Bot"
      ><el-checkbox-group v-model="model.bot_ids" class="grant-grid"
        ><el-checkbox
          v-for="bot in session.bots"
          :key="bot.id"
          :value="bot.id"
          border
          >{{ bot.name
          }}<small
            >{{ platformName(bot.platform)
            }}{{ bot.enabled ? "" : " · 已停用" }}</small
          ></el-checkbox
        ></el-checkbox-group
      ></el-form-item
    ><el-form-item label="默认 Bot"
      ><el-select
        v-model="model.default_bot_id"
        clearable
        placeholder="不设默认，每次调用时指定 Bot"
        ><el-option
          v-for="id in model.bot_ids"
          :key="id"
          :value="id"
          :label="
            session.bots.find((b) => b.id === id)?.name || id
          " /></el-select
    ></el-form-item>
    <p class="help">
      未指定 bot_id 时使用默认 Bot；默认 Bot 必须在授权范围内。未授权任何 Bot
      的密钥不能发送通知。
    </p></el-form
  >
</template>
