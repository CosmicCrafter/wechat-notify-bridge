<script setup>
import { ref, watch, onBeforeUnmount } from "vue";
const props = defineProps({
  cid: { type: String, required: true },
  image: { type: Object, required: true },
  request: { type: Function, required: true },
  pending: Boolean,
});
const emit = defineEmits(["preview"]);
const url = ref(""),
  error = ref(""),
  loading = ref(false);
let generation = 0,
  owned = false;
function release() {
  if (owned && url.value) URL.revokeObjectURL(url.value);
  owned = false;
  url.value = "";
}
async function load() {
  const current = ++generation;
  release();
  error.value = "";
  if (props.image.url) {
    url.value = props.image.url;
    loading.value = false;
    return;
  }
  if (props.pending) {
    loading.value = false;
    error.value = "图片已添加，发送后可查看";
    return;
  }
  loading.value = true;
  try {
    const blob = await props.request(
      `conversations/${props.cid}/images/${props.image.id}`,
      undefined,
      true,
    );
    if (current !== generation) return;
    owned = true;
    url.value = URL.createObjectURL(blob);
  } catch (e) {
    if (current === generation) error.value = e.message || "图片未能加载";
  } finally {
    if (current === generation) loading.value = false;
  }
}
watch(
  [
    () => props.cid,
    () => props.image.id,
    () => props.image.url,
    () => props.pending,
  ],
  load,
  {
    immediate: true,
  },
);
onBeforeUnmount(() => {
  generation++;
  release();
});
</script>
<template>
  <button
    v-if="url"
    type="button"
    class="image-button"
    @click="emit('preview', url)"
  >
    <img :src="url" alt="图片附件，点击放大" loading="lazy" />
  </button>
  <div v-else class="image-placeholder" role="status">
    <span>{{ loading ? "图片加载中…" : error }}</span>
    <el-button v-if="!loading && !pending" text size="small" @click="load"
      >重新加载图片</el-button
    >
  </div>
</template>
