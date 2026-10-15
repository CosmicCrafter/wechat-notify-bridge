// Static Markdown remains readable without JavaScript; local scripts enhance it.
import { createRequire } from "node:module";
import { readFile } from "node:fs/promises";
import { resolve, posix } from "node:path";
const require = createRequire(resolve(process.argv[2], "package.json"));
const { marked, Renderer } = require("marked");
const asset = async (name) =>
  readFile(new URL(`./docs/${name}`, import.meta.url), "utf8");
const navigation = JSON.parse(await asset("navigation.json"));
let input = "";
for await (const chunk of process.stdin) input += chunk;
const data = JSON.parse(input);
const escape = (text) =>
  String(text).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
function render(markdown) {
  const renderer = new Renderer(),
    headings = new Map(),
    toc = [];
  renderer.html = ({ text }) => escape(text);
  renderer.image = ({ text }) => escape(text || "");
  renderer.table = function (token) {
    return `<div class="table-scroll" role="region" aria-label="数据表格" tabindex="0">${Renderer.prototype.table.call(this, token)}</div>`;
  };
  renderer.link = function ({ href, tokens }) {
    const label = this.parser.parseInline(tokens);
    try {
      if (
        !["http:", "https:"].includes(
          new URL(href, "https://docs.example.com/").protocol,
        )
      )
        return label;
    } catch {
      return label;
    }
    return `<a href="${escape(href)}" rel="noopener noreferrer">${label}</a>`;
  };
  renderer.heading = function ({ text, tokens, depth }) {
    const slug = text
      .toLowerCase()
      .replace(/[^\p{L}\p{N}_\- ]/gu, "")
      .replaceAll(" ", "-");
    const count = headings.get(slug) || 0;
    headings.set(slug, count + 1);
    const id = slug + (count ? `-${count}` : "");
    const label = this.parser.parseInline(tokens);
    if (depth === 2 || depth === 3) toc.push({ id, depth, label });
    return `<h${depth} id="${escape(id)}">${label}</h${depth}>`;
  };
  return { html: marked.parse(markdown, { renderer, gfm: true }), toc };
}
const output = {},
  search = [];
const home = await asset("home.html");
for (const page of data.pages) {
  const relative = (target) =>
    posix.relative(posix.dirname(page.path), target) || "./";
  const href = (target) => escape(relative(target));
  const meta = navigation
    .flatMap((g) =>
      g.pages.map((p) => ({
        path: p[0],
        label: p[1],
        summary: p[2],
        group: g.group,
      })),
    )
    .find((p) => p.path === page.path) || {
    label: page.title,
    summary: "开发者接入参考",
    group: "文档",
  };
  const nav = navigation
    .map(
      (g) =>
        `<div class="nav-label">${escape(g.group)}</div>` +
        g.pages
          .filter(([path]) => data.pages.some((p) => p.path === path))
          .map(
            ([path, label]) =>
              `<a class="nav-link" href="${href(path)}"${path === page.path ? ' aria-current="page"' : ""}><span class="nav-mark" aria-hidden="true">▸</span>${escape(label)}</a>`,
          )
          .join(""),
    )
    .join("");
  const rendered = render(page.markdown);
  // Text-only search data, generated with the same Markdown parser as the article.
  const plain = (page.path === "index.html" ? home : rendered.html)
    .replace(/<[^>]+>/g, " ")
    .replace(
      /&(?:amp|lt|gt|quot|#39);/g,
      (m) =>
        ({
          "&amp;": "&",
          "&lt;": "<",
          "&gt;": ">",
          "&quot;": '"',
          "&#39;": "'",
        })[m],
    )
    .replace(/\s+/g, " ")
    .trim();
  search.push({
    path: page.path,
    title: meta.label,
    summary: meta.summary,
    content: plain,
  });
  const footer = `服务 ${escape(data.release.server_version)} · 插件 ${escape(data.release.plugin_version)}`;
  const resources = `<a href="${href(page.markdown_path)}">↗ 阅读 Markdown</a><a href="${href("openapi.json")}">API OpenAPI</a><a href="${href("llms.txt")}">✳ AI 索引</a><a href="${href("download.zip")}">下载文档包</a>`;
  const article = `<main class="doc-main" id="content"><div class="crumbs"><a href="${href("index.html")}">开发文档</a><span>/</span><span>${escape(meta.group)}</span><span>/</span><span>${escape(meta.label)}</span></div><header class="doc-head"><div class="eyebrow"><span class="dot"></span>${escape(meta.group)}</div><h1 id="${escape((rendered.html.match(/<h1 id="([^"]*)"/) || [])[1] || "page-title")}">${escape(page.title)}</h1><p class="subtitle">${escape(meta.summary)}</p><div class="doc-tools">${resources}</div></header><div class="doc-content"><article>${rendered.html.replace(/^<h1\b[^>]*>[\s\S]*?<\/h1>\s*/, "")}</article></div><div class="doc-note"><strong>注意：</strong>公开文档不包含你的服务 Key、Bot Secret 或私人消息。调用接口仍须认证和授权，实例地址以管理员提供值为准。</div><footer class="doc-bottom"><span>${footer}</span><a href="${href("index.html")}">返回文档首页 ↑</a></footer></main><aside class="toc" aria-label="本页目录"><div class="toc-title">本页目录</div>${rendered.toc.map((h) => `<a class="${h.depth === 3 ? "is-level-3" : ""}" href="#${escape(h.id)}">${h.label}</a>`).join("")}<div class="resources"><a href="${href(page.markdown_path)}">阅读纯文本版本 ↗</a></div></aside>`;
  const body =
    page.path === "index.html"
      ? `<main class="doc-main" id="content">${home}<footer class="home-footer"><span>Notify Bridge 开发者文档 · ${footer}</span><span>通用公开资料 · 接口调用另行授权</span></footer></main>`
      : article;
  output[page.path] =
    `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="${escape(meta.summary)}"><title>${escape(meta.label)} · Notify Bridge 开发文档</title><link rel="stylesheet" href="${href("style.css")}"><link rel="alternate" type="text/markdown" title="此页 Markdown 源" href="${href(page.markdown_path)}"><link rel="alternate" type="text/plain" title="AI 文档索引" href="${href("llms.txt")}"><link rel="alternate" type="application/json" title="OpenAPI 3.1" href="${href("openapi.json")}"></head><body data-version="${escape(data.release.server_version)}" data-root="${escape(relative("index.html").replace(/index\.html$/, ""))}"><a class="skip-link" href="#content">跳转正文</a><header class="topbar"><button class="top-icon menu-toggle js-only" id="menuToggle" aria-label="打开文档目录" aria-controls="sidebar" aria-expanded="false">☰</button><a class="brand" href="${href("index.html")}"><span class="brand-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 16V8m5 11V5m5 12V7m5 8v-4"/><path d="M2 20h20"/></svg></span><span>Notify Bridge</span></a><span class="top-sep"></span><span class="edition">开发者文档</span><div class="top-spacer"></div><button class="top-action search-trigger js-only" id="searchOpen"><span class="search-label">⌕ 搜索文档...</span><kbd class="search-label">Ctrl K</kbd><span class="search-mobile-icon" aria-hidden="true">⌕</span><span class="sr-only">搜索文档</span></button><a href="${href("llms.txt")}" class="top-action hide-mobile">AI 索引 ↗</a><button class="top-icon js-only" id="themeToggle" aria-label="切换深色模式">◐</button><span class="version-chip">v${escape(data.release.server_version)}</span></header><div class="screen-overlay" id="screenOverlay"></div><div class="app-shell"><aside class="sidebar" id="sidebar" aria-label="文档目录"><nav>${nav}</nav><div class="side-bottom"><span class="dot"></span><strong>公开文档 · 无需登录</strong><p>阅读与下载通用资料无需身份验证。调用 API、管理连接仍须授权。</p><a href="${href("llms.txt")}">AI 阅读索引 ↗</a></div></aside><div class="page-layout${page.path === "index.html" ? " home-layout" : ""}">${body}</div></div><a id="scrollTop" class="scrolltop js-only" href="#content" aria-label="返回顶部">↑</a><dialog id="searchDialog" class="search-dialog" aria-label="搜索开发者文档"><form class="search-header" method="dialog"><span aria-hidden="true">⌕</span><input id="searchInput" type="search" aria-label="搜索关键词" placeholder="搜索 HTTP、MCP、会话、授权..." autocomplete="off"><button class="close-search" aria-label="关闭搜索">ESC</button></form><div class="search-results" id="searchResults" aria-live="polite"></div><div class="search-bottom">全文搜索 · Ctrl / ⌘ + K 打开 · ESC 关闭</div></dialog><script src="${href("script.js")}" defer></script></body></html>`;
}
output["style.css"] = await asset("site.css");
output["script.js"] = await asset("site.js");
output["search-index.json"] = JSON.stringify({
  release: data.release,
  pages: search,
});
process.stdout.write(JSON.stringify(output));
