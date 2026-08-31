/* Runs in the extension's isolated world only after an operator gesture. */
(function () {
  "use strict";
  if (window.RareIQLabelProbeInstalled) return;
  window.RareIQLabelProbeInstalled = true;
  const core = window.RareIQLabelProbeCore;
  let recorder = null, observer = null, root = null, timer = null, flushTimer = null;
  let state = "stopped", reason = "Not collecting", activeRoom = null, wasMissing = false;

  function entries() {
    const rows = root.querySelectorAll(core.SELECTORS.row);
    if (rows.length > 250) throw new Error("Too many rendered rows; stopped to protect page performance");
    return Array.from(rows).map(node => ({node, parsed: core.parseRow(node)}));
  }
  function detach() {
    observer?.disconnect(); observer = null; root = null;
    clearTimeout(flushTimer); flushTimer = null;
  }
  function stop(message = "Stopped; observations retained in this tab until cleared or reloaded") {
    detach(); clearInterval(timer); timer = null; state = "stopped"; reason = message;
  }
  function flush() {
    flushTimer = null;
    if (core.roomFromUrl(location.href) !== activeRoom) { stop("Room changed; start a new inspection explicitly"); return; }
    if (!root?.isConnected) return;
    try { recorder.ingest(entries()); } catch (error) { stop(error.message); }
  }
  function checkRoot() {
    if (core.roomFromUrl(location.href) !== activeRoom) { stop("Room changed; start a new inspection explicitly"); return; }
    const next = document.querySelector(core.SELECTORS.container);
    if (next === root && root?.isConnected) return;
    if (root || !wasMissing) recorder.coverageGap();
    detach(); wasMissing = !next;
    if (!next) { state = "waiting"; reason = "Chat container missing; coverage gap, no events inferred"; return; }
    root = next;
    try { recorder.ingest(entries(), {baseline: true}); } catch (error) { stop(error.message); return; }
    observer = new MutationObserver(() => {
      if (flushTimer === null) flushTimer = setTimeout(flush, 150);
    });
    observer.observe(root, {childList: true, subtree: true, characterData: true,
      attributes: true, attributeFilter: ["data-e2e", "alt"]});
    state = "observing"; reason = "Off-air: chat, joins, follows, gift and Fan Club notices";
  }
  function start() {
    const room = core.roomFromUrl(location.href);
    if (!room) throw new Error("Open a TikTok /@username/live page first");
    if ((state === "observing" || state === "waiting") && room === activeRoom) return;
    stop();
    recorder = new core.Recorder({room, sessionId: crypto.randomUUID()}); activeRoom = room;
    // Initial attachment is not a reconnect gap.
    wasMissing = true; checkRoot();
    if (state !== "stopped") timer = setInterval(checkRoot, 1000);
  }
  chrome.runtime.onMessage.addListener((message, sender, respond) => {
    if (sender.id !== chrome.runtime.id || message?.channel !== "rareiq-label-probe") return;
    try {
      // Stop/Clear always remain available, including after updating the extension.
      if (message.version && message.version !== core.VERSION && !["stop", "clear"].includes(message.command)) {
        throw new Error("Probe updated; reload the LIVE tab before starting again");
      }
      if (message.command === "start" && message.room && message.room !== core.roomFromUrl(location.href)) {
        throw new Error("LIVE room changed; reopen the probe in the intended room before starting");
      }
      if (activeRoom && core.roomFromUrl(location.href) !== activeRoom) stop("Room changed; start a new inspection explicitly");
      if (message.command === "start") start();
      else if (message.command === "stop") stop();
      else if (message.command === "clear") { stop("Cleared; no observations retained"); recorder = null; activeRoom = null; }
      else if (!["status", "export"].includes(message.command)) throw new Error("Unknown probe command");
      const summary = recorder?.summary();
      respond({ok: true, version: core.VERSION, state, reason, room: activeRoom,
        counters: summary?.counters || {}, buffered: summary?.buffered || 0,
        report: message.command === "export" ? recorder?.report(message.includeText === true) || null : undefined});
    } catch (error) { respond({ok: false, error: error.message}); }
  });
  window.addEventListener("pagehide", () => stop("Page closed or navigating"), {once: true});
})();
