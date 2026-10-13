import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { mkdir, writeFile, readFile } from "node:fs/promises";
const root = dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2),
  ix = args.indexOf("--deps-dir");
const deps =
  ix >= 0
    ? resolve(args[ix + 1])
    : resolve(root, "../../../frontend/node_modules");
const require = createRequire(resolve(deps, "../package.json"));
const { build } = await import(pathToFileURL(require.resolve("vite")).href);
const { default: vue } = await import(
  pathToFileURL(require.resolve("@vitejs/plugin-vue")).href
);
const { default: Components } = await import(
  pathToFileURL(require.resolve("unplugin-vue-components/vite")).href
);
const { ElementPlusResolver } = await import(
  pathToFileURL(require.resolve("unplugin-vue-components/resolvers")).href
);
const out = resolve(root, "../prototype");
await mkdir(out, { recursive: true });
await build({
  configFile: false,
  root,
  plugins: [
    vue(),
    Components({ dts: false, resolvers: [ElementPlusResolver()] }),
  ],
  resolve: {
    alias: {
      vue: resolve(deps, "vue"),
      "element-plus": resolve(deps, "element-plus"),
      "@element-plus/icons-vue": resolve(deps, "@element-plus/icons-vue"),
    },
  },
  define: { "process.env.NODE_ENV": '"production"' },
  build: {
    outDir: out,
    emptyOutDir: false,
    cssCodeSplit: false,
    minify: "esbuild",
    lib: {
      entry: resolve(root, "main.js"),
      name: "NotifyBridgePrototype",
      formats: ["iife"],
      fileName: () => "app.js",
      cssFileName: "style",
    },
    rollupOptions: { output: { inlineDynamicImports: true } },
    chunkSizeWarningLimit: 1200,
  },
});
await writeFile(
  resolve(out, "index.html"),
  `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'self' data: blob:; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'none'; img-src 'self' data: blob:; font-src 'self'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"><title>Notify Bridge · 管理原型</title><link rel="stylesheet" href="style.css"></head><body><div id="app"></div><script src="app.js" defer></script></body></html>`,
);
await writeFile(
  resolve(out, "THIRD-PARTY-NOTICES.md"),
  (
    await readFile(
      resolve(root, "../../../frontend/THIRD-PARTY-NOTICES.md"),
      "utf8",
    )
  ).replace(/[ \t]+$/gm, ""),
);
console.log("Offline prototype built. No production resources were changed.");
