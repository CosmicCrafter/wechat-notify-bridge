// Build static public HTML with the project's existing Markdown parser. No runtime JS or CDN.
import { createRequire } from "node:module";
import { resolve, posix } from "node:path";
const require = createRequire(resolve(process.argv[2], "package.json"));
const { marked, Renderer } = require("marked");
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
  const renderer = new Renderer();
  const headings = new Map();
  renderer.html = ({ text }) => escape(text);
  renderer.image = ({ text }) => escape(text || "");
  renderer.table = function (token) {
    return `<div class="table-scroll">${Renderer.prototype.table.call(this, token)}</div>`;
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
    return `<h${depth} id="${escape(id)}">${this.parser.parseInline(tokens)}</h${depth}>`;
  };
  return marked.parse(markdown, { renderer, gfm: true });
}
const topics = [
  ["index.html", "接入总览"],
  ["integration/HTTP.html", "HTTP 与示例"],
  ["integration/CLIENT-SETUP.html", "Codex / Claude MCP"],
  ["integration/RECEIVERS.html", "会话与接收协议"],
  ["server/API.html", "API 与错误说明"],
  ["server/TASK-CARDS.html", "任务卡片"],
  ["server/DELIVERY-RELIABILITY.html", "投递与重试"],
];
const output = {};
for (const page of data.pages) {
  const relative = (target) => posix.relative(posix.dirname(page.path), target);
  const nav = topics
    .map(
      ([path, label]) =>
        `<a href="${relative(path)}"${path === page.path ? ' aria-current="page"' : ""}>${label}</a>`,
    )
    .join("");
  output[page.path] =
    `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escape(page.title)} · Notify Bridge</title><link rel="stylesheet" href="${relative("style.css")}"></head><body><header><a class="brand" href="${relative("index.html")}">↗ Notify Bridge</a><span>公开开发文档</span><small>服务 ${escape(data.release.server_version)} · 插件 ${escape(data.release.plugin_version)}</small></header><div class="docs-shell"><aside><nav aria-label="开发文档导航">${nav}</nav><p class="help">阅读文档无需登录。调用接口仍需应用授权，管理功能和消息记录保持鉴权。</p></aside><main><div class="doc-actions"><a href="${relative(page.markdown_path)}">读取 Markdown</a><a href="${relative("openapi.json")}">OpenAPI</a><a href="${relative("examples/python/notify_bridge.py")}">Python 示例</a><a href="${relative("download.zip")}">下载公开文档</a></div><article>${render(page.markdown)}</article><footer>通用资料不包含实例配置或真实凭据。实际接入地址和权限由服务维护者提供；旧 /openapi.json 仍需应用认证。</footer></main></div></body></html>`;
}
output["style.css"] =
  data.theme +
  `
body{line-height:1.75}header{display:flex;align-items:center;gap:20px;flex-wrap:wrap;padding:20px 5%;background:#fff;border-bottom:1px solid #e7ebf2}.brand{font-size:20px;font-weight:750}header small{margin-left:auto;color:#7b8799}.docs-shell{display:grid;grid-template-columns:240px minmax(0,1fr);max-width:1320px;margin:24px auto;padding:0 24px;gap:28px}aside{align-self:start;position:sticky;top:24px}nav{display:flex;flex-direction:column;gap:6px}nav a{padding:10px 14px;border-radius:8px;color:#40506a}nav a:hover,nav a[aria-current]{background:#e9efff;color:var(--el-color-primary)}main{min-width:0;background:#fff;border:1px solid #e7ebf2;border-radius:12px;padding:30px 36px}.doc-actions{display:flex;flex-wrap:wrap;gap:16px;font-size:14px;padding-bottom:18px;border-bottom:1px solid #e7ebf2;margin-bottom:24px}article h1{margin-bottom:18px}article h2{margin-top:32px;padding-top:10px}article h3{margin-top:24px}pre{overflow:auto;background:#f4f6fa;border:1px solid #e3e8f1;border-radius:8px;padding:16px;line-height:1.6}code{font-family:Consolas,monospace;font-size:.9em;overflow-wrap:anywhere}p code,li code,td code{background:#f1f4fa;padding:2px 5px;border-radius:4px}.table-scroll{max-width:100%;overflow-x:auto}table{width:100%;min-width:600px;border-collapse:collapse;font-size:14px}th{white-space:nowrap}th,td{text-align:left;vertical-align:top;border:1px solid #dfe5ee;padding:10px 12px}th{background:#f5f7fb}blockquote{margin:16px 0;padding:10px 18px;border-left:3px solid var(--el-color-primary);background:#f5f7fd}footer{margin-top:36px;border-top:1px solid #e7ebf2;padding-top:18px;color:#7b8799;font-size:12px}:target{scroll-margin-top:20px}a:hover{text-decoration:underline}@media(max-width:760px){header{padding:16px;gap:8px 16px}header small{width:100%;margin-left:0}.docs-shell{display:block;padding:0 12px;margin:16px auto}aside{position:static;margin-bottom:16px}nav{flex-direction:row;flex-wrap:wrap;gap:4px}nav a{font-size:13px;padding:7px 10px}aside .help{margin:8px}main{padding:20px 16px}article h1{font-size:24px}.doc-actions{gap:10px 16px}}
`;
process.stdout.write(JSON.stringify(output));
