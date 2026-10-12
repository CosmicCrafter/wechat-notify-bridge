<script setup>
import { computed } from "vue";
import { marked } from "marked";
import DOMPurify from "dompurify";
const props = defineProps({
  text: { type: String, default: "" },
  base: { type: String, default: "" },
});
const html = computed(() => {
  const fragment = DOMPurify.sanitize(
    marked.parse(props.text, { breaks: true, gfm: true }),
    {
      RETURN_DOM_FRAGMENT: true,
      ALLOWED_TAGS: [
        "p",
        "br",
        "strong",
        "em",
        "del",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "ul",
        "ol",
        "li",
        "blockquote",
        "pre",
        "code",
        "hr",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "a",
      ],
      ALLOWED_ATTR: ["href", "title", "start"],
    },
  );
  for (const a of fragment.querySelectorAll("a")) {
    try {
      const u = new URL(a.getAttribute("href"), props.base || location.href);
      if (!["https:", "http:"].includes(u.protocol)) throw Error();
      a.href = u.href;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
    } catch {
      a.removeAttribute("href");
    }
  }
  const div = document.createElement("div");
  div.append(fragment);
  return div.innerHTML;
});
</script>
<template><div class="markdown" v-html="html"></div></template>
