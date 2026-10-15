// Progressive enhancement only: article, navigation and resource links are static HTML.
(() => {
  document.documentElement.classList.add("js");
  const q = (s) => document.querySelector(s);
  const root = new URL(document.body.dataset.root || "./", document.baseURI);
  const dialog = q("#searchDialog"),
    input = q("#searchInput"),
    results = q("#searchResults");
  let index,
    loading,
    failed = false;
  const norm = (text) => text.normalize("NFKC").toLocaleLowerCase();
  const message = (text, retry = false) => {
    const box = document.createElement("div");
    box.className = "search-empty";
    box.textContent = text;
    if (retry) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = "重新加载";
      b.addEventListener("click", async () => {
        await load();
        input.focus();
      });
      box.append(b);
    }
    results.replaceChildren(box);
  };
  const draw = () => {
    if (!index) return;
    const term = input.value.trim().slice(0, 200),
      terms = norm(term).split(/\s+/).filter(Boolean);
    const matches = index
      .map((d) => {
        const title = norm(d.title),
          summary = norm(d.summary),
          content = norm(d.content);
        return {
          d,
          score: terms.every(
            (t) =>
              title.includes(t) || summary.includes(t) || content.includes(t),
          )
            ? terms.reduce(
                (n, t) =>
                  n +
                  (title.includes(t) ? 10 : 0) +
                  (summary.includes(t) ? 3 : 0) +
                  (content.includes(t) ? 1 : 0),
                1,
              )
            : 0,
        };
      })
      .filter((x) => x.score)
      .sort((a, b) => b.score - a.score)
      .slice(0, 20);
    if (!matches.length)
      return message("没有找到匹配内容。可以尝试 HTTP、MCP、会话或 Key。");
    const fragment = document.createDocumentFragment();
    for (const { d } of matches) {
      const target = new URL(d.path, root);
      if (target.origin !== root.origin || !target.href.startsWith(root.href))
        continue;
      const a = document.createElement("a");
      a.className = "search-result";
      a.href = target.href;
      const title = document.createElement("span");
      title.className = "result-title";
      title.textContent = d.title;
      const snippet = document.createElement("span");
      snippet.className = "result-description";
      const position = terms.length
        ? Math.max(0, norm(d.content).indexOf(terms[0]) - 38)
        : 0;
      snippet.textContent = term
        ? `${position ? "…" : ""}${d.content.slice(position, position + 150)}…`
        : d.summary;
      a.append(title, snippet);
      fragment.append(a);
    }
    results.replaceChildren(fragment);
  };
  async function load() {
    if (index) return draw();
    if (loading) return loading;
    failed = false;
    message("正在加载全文索引…");
    loading = (async () => {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 8000);
      try {
        const response = await fetch(new URL("search-index.json", root), {
          credentials: "omit",
          signal: controller.signal,
        });
        if (!response.ok) throw new Error("index unavailable");
        const data = await response.json();
        if (
          !Array.isArray(data.pages) ||
          data.release.server_version !== document.body.dataset.version
        )
          throw new Error("index version mismatch");
        index = data.pages;
        draw();
      } catch {
        failed = true;
        message("搜索索引暂时不可用，仍可使用左侧目录阅读文档。", true);
      } finally {
        clearTimeout(timeout);
        loading = null;
      }
    })();
    return loading;
  }
  const menu = q("#menuToggle"),
    sidebar = q("#sidebar"),
    overlay = q("#screenOverlay");
  const mobile = matchMedia("(max-width:860px)");
  const setNav = (open, restore = false) => {
    sidebar.classList.toggle("is-open", open);
    overlay.classList.toggle("active", open);
    document.documentElement.classList.toggle(
      "nav-open",
      open && mobile.matches,
    );
    menu.setAttribute("aria-expanded", String(open));
    sidebar.inert = mobile.matches && !open;
    q(".page-layout").inert = mobile.matches && open;
    if (open && mobile.matches) sidebar.querySelector("a")?.focus();
    if (!open && restore) menu.focus();
  };
  setNav(false);
  mobile.addEventListener("change", () => setNav(false));
  menu.addEventListener("click", () =>
    setNav(!sidebar.classList.contains("is-open")),
  );
  overlay.addEventListener("click", () => setNav(false, true));
  const openSearch = () => {
    setNav(false);
    if (dialog.open) return;
    dialog.showModal();
    document.documentElement.classList.add("search-open");
    input.value = "";
    input.focus();
    load();
  };
  q("#searchOpen").addEventListener("click", openSearch);
  input.addEventListener("input", () => {
    if (!failed) draw();
  });
  dialog.addEventListener("close", () => {
    document.documentElement.classList.remove("search-open");
    q("#searchOpen").focus();
  });
  dialog.addEventListener("click", (e) => {
    if (e.target === dialog) dialog.close();
  });
  window.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      openSearch();
    }
    if (e.key === "Escape" && sidebar.classList.contains("is-open"))
      setNav(false, true);
    if (dialog.open && e.key === "Enter" && document.activeElement === input) {
      e.preventDefault();
      results.querySelector("a")?.click();
    }
    if (dialog.open && ["ArrowDown", "ArrowUp"].includes(e.key)) {
      const links = [...results.querySelectorAll("a")];
      if (!links.length) return;
      e.preventDefault();
      let i = links.indexOf(document.activeElement);
      i = (i + (e.key === "ArrowDown" ? 1 : -1) + links.length) % links.length;
      links[i].focus();
    }
  });
  const copy = async (text) => {
    let timeout;
    try {
      if (navigator.clipboard?.writeText) {
        await Promise.race([
          navigator.clipboard.writeText(text),
          new Promise((_, reject) => {
            timeout = setTimeout(
              () => reject(new Error("clipboard timeout")),
              2500,
            );
          }),
        ]);
        return true;
      }
    } catch {
      /* selection fallback */
    } finally {
      clearTimeout(timeout);
    }
    const textarea = document.createElement("textarea");
    textarea.className = "sr-only";
    textarea.value = text;
    const active = document.activeElement;
    document.body.append(textarea);
    textarea.select();
    let ok = false;
    try {
      ok = document.execCommand("copy");
    } catch {
      /* report failure accurately */
    }
    textarea.remove();
    active?.focus();
    return ok;
  };
  const copied = async (button, text) => {
    const original = button.textContent;
    button.disabled = true;
    button.textContent = "正在复制…";
    const ok = await copy(text);
    button.disabled = false;
    button.textContent = ok ? "已复制" : "复制失败，请手动选择";
    button.setAttribute("aria-label", button.textContent);
    setTimeout(() => {
      button.textContent = original;
      button.setAttribute("aria-label", original);
    }, 1800);
  };
  document.querySelectorAll("pre > code").forEach((code) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "copy-btn";
    button.textContent = "复制代码";
    button.setAttribute("aria-label", "复制代码");
    button.setAttribute("aria-live", "polite");
    code.parentElement.append(button);
    button.addEventListener("click", () => copied(button, code.textContent));
  });
  document.querySelectorAll("[data-docs-url]").forEach((el) => {
    el.textContent = root.href;
  });
  document
    .querySelectorAll("[data-copy-root]")
    .forEach((b) => b.addEventListener("click", () => copied(b, root.href)));
  const toggle = q("#themeToggle");
  const apply = (value) => {
    document.documentElement.dataset.theme = value;
    toggle.setAttribute(
      "aria-label",
      value === "dark" ? "切换浅色模式" : "切换深色模式",
    );
    toggle.textContent = value === "dark" ? "☀" : "◐";
  };
  let saved;
  try {
    saved = localStorage.getItem("notify-bridge-docs-theme");
  } catch {
    /* storage unavailable */
  }
  apply(
    ["dark", "light"].includes(saved)
      ? saved
      : matchMedia("(prefers-color-scheme:dark)").matches
        ? "dark"
        : "light",
  );
  toggle.addEventListener("click", () => {
    const value =
      document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    apply(value);
    try {
      localStorage.setItem("notify-bridge-docs-theme", value);
    } catch {
      /* usable without persistence */
    }
  });
  const top = q("#scrollTop"),
    scroll = () => top.classList.toggle("visible", window.scrollY > 320);
  scroll();
  window.addEventListener("scroll", scroll, { passive: true });
  const toc = [...document.querySelectorAll(".toc a[href^='#']")];
  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries.find((e) => e.isIntersecting);
        if (!entry) return;
        toc.forEach((a) => {
          const active =
            decodeURIComponent(a.hash.slice(1)) === entry.target.id;
          a.classList.toggle("is-active", active);
          if (active) a.setAttribute("aria-current", "location");
          else a.removeAttribute("aria-current");
        });
      },
      { rootMargin: "-80px 0px -65% 0px" },
    );
    document
      .querySelectorAll("article h2,article h3")
      .forEach((h) => observer.observe(h));
  }
})();
