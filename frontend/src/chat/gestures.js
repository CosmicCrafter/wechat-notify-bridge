// Native pointer/touch gestures with click suppression and cleanup.
export const vLongpress = {
  mounted(el, binding) {
    let timer,
      start,
      suppress = 0;
    const cancel = () => {
      clearTimeout(timer);
      start = null;
    };
    const open = () => {
      cancel();
      suppress = Date.now() + 900;
      binding.value();
    };
    const events = {
      pointerdown: (e) => {
        if (e.button !== 0 || !e.isPrimary) return;
        start = { x: e.clientX, y: e.clientY };
        timer = setTimeout(open, 500);
      },
      pointermove: (e) => {
        if (start && Math.hypot(e.clientX - start.x, e.clientY - start.y) > 10)
          cancel();
      },
      pointerup: cancel,
      pointercancel: cancel,
      pointerleave: cancel,
      lostpointercapture: cancel,
      contextmenu: (e) => {
        e.preventDefault();
        if (Date.now() > suppress) open();
      },
      keydown: (e) => {
        if (e.key === "ContextMenu" || (e.shiftKey && e.key === "F10")) {
          e.preventDefault();
          open();
        }
      },
      click: (e) => {
        if (Date.now() < suppress) {
          e.preventDefault();
          e.stopImmediatePropagation();
        }
      },
    };
    for (const [event, fn] of Object.entries(events))
      el.addEventListener(event, fn, event === "click");
    el._longCleanup = () => {
      cancel();
      for (const [event, fn] of Object.entries(events))
        el.removeEventListener(event, fn, event === "click");
    };
  },
  unmounted(el) {
    el._longCleanup?.();
  },
};
export const vSwipe = {
  mounted(el, binding) {
    let start;
    const begin = (e) => {
      const t = e.touches[0];
      start =
        e.touches.length === 1 &&
        !e.target.closest("textarea,input,pre,.markdown table")
          ? { x: t.clientX, y: t.clientY }
          : null;
    };
    const end = (e) => {
      if (!start) return;
      const t = e.changedTouches[0],
        dx = t.clientX - start.x,
        dy = t.clientY - start.y;
      if (Math.abs(dx) > 75 && Math.abs(dy) < 25) {
        if (binding.value.edge && start.x >= 32) return;
        binding.value.action(dx > 0 ? "right" : "left");
      }
      start = null;
    };
    el.addEventListener("touchstart", begin, { passive: true });
    el.addEventListener("touchend", end, { passive: true });
    el._swipeCleanup = () => {
      el.removeEventListener("touchstart", begin);
      el.removeEventListener("touchend", end);
    };
  },
  unmounted(el) {
    el._swipeCleanup?.();
  },
};
