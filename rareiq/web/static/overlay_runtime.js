/* Shared browser-source transport: one request batch, bounded lifetime, safe clear. */
window.RareIQOverlay = (() => {
  async function json(path, signal) {
    const response = await fetch(path, {cache: "no-store", signal});
    if (!response.ok) throw new Error("Overlay endpoint unavailable");
    const payload = await response.json();
    if (payload?.ok === false) throw new Error("Overlay state unavailable");
    return payload;
  }

  function start({load, render, clear, interval = 750, timeout = 4000}) {
    let stopped = false, timer = 0, deadline = 0, controller;
    async function poll() {
      if (stopped) return;
      controller = new AbortController();
      const signal = controller.signal;
      const aborted = new Promise((_, reject) => {
        signal.addEventListener("abort", () => reject(new Error("Overlay request expired")), {once: true});
      });
      deadline = setTimeout(() => controller.abort(), timeout);
      try {
        const payload = await Promise.race([load(signal), aborted]);
        if (!stopped && !signal.aborted) render(payload);
      } catch {
        clear();
      } finally {
        clearTimeout(deadline);
        if (!stopped) timer = setTimeout(poll, interval);
      }
    }
    function stop() {
      stopped = true;
      clearTimeout(timer);
      clearTimeout(deadline);
      controller?.abort();
      clear();
    }
    window.addEventListener("pagehide", stop, {once: true});
    poll();
    return stop;
  }
  return {json, start};
})();
