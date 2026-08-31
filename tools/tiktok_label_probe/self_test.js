(function () {
  "use strict";
  const core = window.RareIQLabelProbeCore;
  const container = document.querySelector(core.SELECTORS.container);
  const result = document.getElementById("result"), details = document.getElementById("details");
  const button = document.getElementById("run");
  function makeRow(name, text, marker = "chat-message") {
    const row = document.createElement("div"); row.dataset.e2e = marker;
    const avatar = document.createElement("div"), column = document.createElement("div");
    const header = document.createElement("div"), owner = document.createElement("div"), body = document.createElement("div");
    owner.dataset.e2e = "message-owner-name"; owner.textContent = name;
    body.textContent = text; header.append(owner); column.append(header, body); row.append(avatar, column);
    return row;
  }
  function makeFollow() {
    const row = makeRow("Synthetic follower", "followed the host", "social-message");
    const column = row.children[1], header = column.children[0], body = document.createElement("span");
    body.textContent = "followed the host";
    const wrapper = document.createElement("div"); wrapper.append(header, body); column.replaceChildren(wrapper);
    const virtualRow = document.createElement("div"); virtualRow.dataset.index = "3"; virtualRow.append(row);
    return virtualRow;
  }
  function makeFanNotice() {
    const wrapper = document.createElement("div"); wrapper.dataset.index = "4";
    const row = document.createElement("div"), icon = document.createElement("div"), body = document.createElement("div");
    icon.append(document.createElementNS("http://www.w3.org/2000/svg", "svg"));
    body.textContent = "Synthetic member became the No. 72 fan in the Fan Club";
    row.append(icon, body); wrapper.append(row); return wrapper;
  }
  function makeGiftNotice() {
    const wrapper = document.createElement("div"); wrapper.dataset.index = "5";
    const row = document.createElement("div"), icon = document.createElement("div"), body = document.createElement("div");
    const header = document.createElement("div"), owner = document.createElement("div"), badge = document.createElement("span");
    const name = document.createElement("span"), image = document.createElement("span");
    icon.append(document.createElementNS("http://www.w3.org/2000/svg", "svg"));
    owner.dataset.e2e = "message-owner-name"; owner.textContent = "Synthetic sender";
    badge.textContent = "18"; header.append(badge, owner); name.textContent = "Heart Me";
    image.append(document.createElement("img")); // No asset URL or network request.
    body.append(header, document.createTextNode(" sent "), name, image,
      document.createTextNode(" × "), document.createTextNode("1"));
    row.append(icon, body); wrapper.append(row); return wrapper;
  }
  function entries() { return Array.from(container.querySelectorAll(core.SELECTORS.row)).map(node => ({node, parsed: core.parseRow(node)})); }
  button.addEventListener("click", async () => {
    button.disabled = true; let observer = null;
    try {
      container.replaceChildren(makeRow("Synthetic history", "Do not replay"));
      const recorder = new core.Recorder({room: "tiktok:@synthetic", sessionId: "offline-test"});
      recorder.ingest(entries(), {baseline: true});
      async function observeChange(change) {
        await new Promise((resolve, reject) => {
          const deadline = setTimeout(() => reject(new Error("Observer did not fire")), 2000);
          observer = new MutationObserver(() => {
            try { recorder.ingest(entries()); clearTimeout(deadline); resolve(); }
            catch (error) { clearTimeout(deadline); reject(error); }
          });
          observer.observe(container, {childList: true, subtree: true, characterData: true});
          change();
        });
        observer.disconnect();
      }
      const gift = makeGiftNotice();
      await observeChange(() => container.append(makeRow("Synthetic viewer A", "<b>This remains plain text</b>"),
        makeRow("Synthetic viewer B", "joined", "enter-message"), makeFollow(), makeFanNotice(), gift));
      await observeChange(() => { gift.children[0].children[1].childNodes[5].data = "2"; });
      const report = recorder.report(true);
      if (report.events.map(event => event.type).join() !== "chat.message,viewer.join.observed,viewer.follow.observed,viewer.fan_club_notice.observed,gift.notice.observed,gift.notice.observed") throw new Error("Event mapping failed");
      if (report.events[3].actor.display_name !== null || report.events[3].provider_event_id !== null) throw new Error("Unattributed notice acquired a false identity");
      if (report.events[4].gift.displayed_quantity !== 1 || report.events[5].gift.displayed_quantity !== 2
          || report.events[5].gift.streak_complete !== null || report.events[5].gift.quantity_semantics !== "unknown") throw new Error("Gift display observation changed semantics");
      if (container.querySelector("b") || report.events[0].text !== "<b>This remains plain text</b>") throw new Error("Plain-text handling failed");
      if (report.events.some(event => event.eligible_for_actions || event.eligible_for_contributions || event.actor.id !== null)) throw new Error("Safety boundary failed");
      if (recorder.report().events[0].actor.display_name !== "[redacted]" || recorder.report().events[4].actor.display_name !== "[redacted]") throw new Error("Export redaction failed");
      result.textContent = "PASS · native DOM and MutationObserver";
      details.textContent = "History skipped; all five notice types mapped; gift quantity changes observed, not summed; list index not used as an ID; text not executed; exports redacted; production actions disabled.";
    } catch (error) { result.textContent = "FAIL"; details.textContent = error.message; }
    finally { observer?.disconnect(); button.disabled = false; }
  });
})();
