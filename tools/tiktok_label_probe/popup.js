(function () {
  "use strict";
  const $ = id => document.getElementById(id), core = window.RareIQLabelProbeCore;
  if (typeof chrome === "undefined" || !chrome.tabs?.query || !chrome.scripting?.executeScript) {
    $("status").textContent = "Preview only · not connected";
    $("detail").textContent = "Load this folder as an unpacked extension to inspect a LIVE tab.";
    for (const id of ["start", "stop", "export", "clear", "includeText"]) $(id).disabled = true;
    return;
  }
  const CANCELLED = new Error("Superseded command");
  let generation = 0, manualRequests = 0, polling = false, closed = false, targetTab = null;

  // Chrome API promises can stall when a tab navigates or becomes unresponsive.
  // A timeout must show unknown state, never a false confirmation that Stop worked.
  function bounded(promise) {
    let timer;
    return Promise.race([promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error("Tab did not respond. Collection state is unknown; reload the LIVE tab to stop it.")), 4000);
    })]).finally(() => clearTimeout(timer));
  }
  function current(ticket) { if (closed || ticket !== generation) throw CANCELLED; }

  async function send(command, ticket) {
    if (!targetTab) {
      const [tab] = await bounded(chrome.tabs.query({active: true, currentWindow: true}));
      current(ticket);
      if (!tab?.id || !core.roomFromUrl(tab.url)) throw new Error("Open a TikTok /@username/live page, then reopen this probe");
      targetTab = tab; // Keep Stop aimed at this tab, not whichever tab becomes active.
    }
    const message = {channel: "rareiq-label-probe", command, version: core.VERSION,
      room: core.roomFromUrl(targetTab.url), includeText: $("includeText").checked};
    current(ticket);
    try { return await bounded(chrome.tabs.sendMessage(targetTab.id, message)); }
    catch (error) {
      current(ticket);
      // Only the specific missing receiver error permits first-time injection.
      // Timeouts and permission/navigation errors never trigger a second Start.
      if (!/Receiving end does not exist|Could not establish connection/i.test(error.message)) throw error;
      if (command !== "start") throw new Error("No collector responded. Start inspection first, or reload the LIVE tab to ensure it is stopped.");
      await bounded(chrome.scripting.executeScript({target: {tabId: targetTab.id}, files: ["core.js", "content.js"]}));
      current(ticket); // Stop pressed during injection cancels the pending Start.
      return bounded(chrome.tabs.sendMessage(targetTab.id, message));
    }
  }
  function paint(result, command) {
    if (!result?.ok) throw new Error(result?.error || "No response from this tab");
    if (result.version !== core.VERSION && !["stop", "clear"].includes(command)) throw new Error("Probe updated; reload the LIVE tab before starting again");
    if (!["observing", "waiting", "stopped"].includes(result.state)) throw new Error("Unrecognized collector state; reload the LIVE tab to stop it");
    $("status").textContent = result.state === "observing" ? "Observing · off air" : result.state === "waiting" ? "Waiting for chat" : "Stopped";
    const counts = result.counters || {};
    $("detail").textContent = result.reason + (counts.malformed_rows ? ` · ${counts.malformed_rows} changed/unmapped rows skipped` : "");
    $("observed").textContent = counts.observed || 0;
    $("buffered").textContent = result.buffered;
    $("ambiguous").textContent = counts.ambiguous_repeats_skipped || 0;
    $("gaps").textContent = counts.coverage_gaps || 0;
  }
  async function run(command, quiet = false) {
    if (closed || (quiet && (polling || manualRequests))) return;
    const ticket = quiet ? generation : ++generation;
    if (quiet) polling = true;
    else {
      manualRequests++;
      $("status").textContent = command === "stop" ? "Stopping…" : command === "clear" ? "Clearing…" : "Contacting tab…";
    }
    try {
      const result = await send(command, ticket);
      current(ticket); paint(result, command);
      if (command === "export") {
        if (!result.report) throw new Error("No inspection to export yet");
        const blob = new Blob([JSON.stringify(result.report, null, 2)], {type: "application/json"});
        const url = URL.createObjectURL(blob), link = document.createElement("a");
        link.href = url; link.download = `rareiq-label-probe-${Date.now()}.json`; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
    } catch (error) {
      if (error !== CANCELLED && !closed && ticket === generation) {
        $("status").textContent = "Connection unconfirmed"; $("detail").textContent = error.message;
      }
    } finally { if (quiet) polling = false; else manualRequests--; }
  }
  for (const id of ["start", "stop", "export", "clear"]) $(id).addEventListener("click", () => run(id));
  run("status", true);
  const refresh = setInterval(() => run("status", true), 1000);
  window.addEventListener("pagehide", () => { closed = true; generation++; clearInterval(refresh); }, {once: true});
})();
