import { build } from "vite";
import vue from "@vitejs/plugin-vue";
import Components from "unplugin-vue-components/vite";
import { ElementPlusResolver } from "unplugin-vue-components/resolvers";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { mkdir, writeFile, readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
const root = dirname(fileURLToPath(import.meta.url));
const only = process.env.BUILD_PAGE;
for (const page of only ? [only] : ["admin", "chat", "oauth"]) {
  const out = resolve(root, "../server/src/wechat_bridge/web", page);
  await mkdir(out, { recursive: true });
  await build({
    configFile: false,
    root,
    plugins: [
      vue(),
      Components({ dts: false, resolvers: [ElementPlusResolver()] }),
    ],
    define: { "process.env.NODE_ENV": '"production"' },
    build: {
      outDir: out,
      emptyOutDir: false,
      cssCodeSplit: false,
      minify: "esbuild",
      lib: {
        entry: resolve(root, `src/${page}/main.js`),
        name: "NotifyBridge",
        formats: ["iife"],
        fileName: () => "app.js",
        cssFileName: "style",
      },
      rollupOptions: { output: { inlineDynamicImports: true } },
      chunkSizeWarningLimit: 1200,
    },
  });
  const prefix =
    page === "chat" ? "assets/" : page === "oauth" ? "../assets/" : "";
  const css = page === "oauth" ? "style.css" : prefix + "style.css";
  await writeFile(
    resolve(out, "index.html"),
    `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>通知桥</title><link rel="stylesheet" href="${css}"></head><body><div id="app"></div><script src="${page === "oauth" ? "" : prefix}app.js" defer></script></body></html>`,
  );
}

if (!only) {
  const { readdir } = await import("node:fs/promises");
  const inputs = {};
  async function inputHash(path) {
    const bytes = await readFile(path);
    const content = /\.(vue|m?js|css|json)$/.test(path)
      ? bytes.toString("utf8").replace(/\r\n/g, "\n")
      : bytes;
    return createHash("sha256").update(content).digest("hex");
  }
  async function collect(dir) {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const p = resolve(dir, entry.name);
      if (entry.isDirectory()) await collect(p);
      else
        inputs[p.slice(root.length + 1).replaceAll("\\", "/")] =
          await inputHash(p);
    }
  }
  await collect(resolve(root, "src"));
  for (const name of ["build.mjs", "package.json", "package-lock.json"])
    inputs[name] = await inputHash(resolve(root, name));
  const outputs = {};
  for (const page of ["admin", "chat", "oauth"])
    for (const file of ["index.html", "app.js", "style.css"])
      outputs[page + "/" + file] = createHash("sha256")
        .update(
          await readFile(
            resolve(root, "../server/src/wechat_bridge/web", page, file),
          ),
        )
        .digest("hex");
  await writeFile(
    resolve(root, "build-manifest.json"),
    JSON.stringify({ inputs, outputs }, null, 2) + "\n",
  );
}
