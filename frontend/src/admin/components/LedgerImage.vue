<script setup>
import { ref, onMounted, onBeforeUnmount } from "vue";
import { api } from "../session.js";
const props = defineProps({ cid: String, image: Object });
const url = ref(""),
  error = ref("");
let alive = true;
onMounted(async () => {
  try {
    const blob = await api(
      "conversations/" + props.cid + "/images/" + props.image.id,
      undefined,
      true,
    );
    if (alive) url.value = URL.createObjectURL(blob);
  } catch (e) {
    if (alive) error.value = e.message;
  }
});
onBeforeUnmount(() => {
  alive = false;
  if (url.value) URL.revokeObjectURL(url.value);
});
</script>
<template>
  <a v-if="url" :href="url" target="_blank" rel="noopener"
    ><img class="ledger-image" :src="url" alt="会话图片附件，点击查看原图"
  /></a>
  <p v-else class="help">{{ error || "图片加载中…" }}</p>
</template>
