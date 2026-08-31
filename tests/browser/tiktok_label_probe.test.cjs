const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const folder = path.resolve(__dirname, "../../tools/tiktok_label_probe");
const core = require(path.join(folder, "core.js"));

// Synthetic users/messages; structural fixture from public DOM inspected 2026-08-30.
class Element {
  constructor(tag = "div", attrs = {}, children = []) {
    this.tagName = tag.toUpperCase(); this.nodeType = 1; this.attrs = attrs;
    this.childNodes = children.map(child => typeof child === "string" ? {nodeType: 3, textContent: child} : child);
    for (const child of this.children) child.parentElement = this;
  }
  get children() { return this.childNodes.filter(child => child.nodeType === 1); }
  get textContent() { return this.childNodes.map(child => child.textContent).join(""); }
  getAttribute(name) { return this.attrs[name] || null; }
  contains(node) { return this === node || this.children.some(child => child.contains(node)); }
  querySelectorAll(selector) {
    const markers = Array.from(selector.matchAll(/data-e2e="([^"]+)"/g), match => match[1]);
    return this.children.flatMap(child => [ ...(markers.includes(child.attrs["data-e2e"]) ? [child] : []), ...child.querySelectorAll(selector)]);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}
const el = (tag, attrs, children) => new Element(tag, attrs, children);
function row({marker = "chat-message", name = "Test Viewer", text = "Hello", badge = "29", extra = []} = {}) {
  const owner = el("div", {"data-e2e": "message-owner-name", title: name}, [name]);
  const header = el("div", {}, [el("span", {}, [badge]), owner]);
  const body = el("div", {}, [text, ...extra]);
  return el("div", {"data-e2e": marker}, [el("div", {}, [el("img", {src: "https://invalid.test/avatar"})]), el("div", {}, [header, body])]);
}
function followRow(text = "followed the host") {
  const owner = el("div", {"data-e2e": "message-owner-name"}, ["Synthetic follower"]);
  const notice = el("div", {}, [el("div", {}, [el("span", {}, ["5"]), owner]), el("span", {}, [text])]);
  return el("div", {"data-e2e": "social-message"}, [el("div", {}, [el("svg")]), el("div", {}, [notice])]);
}
function fanRow(text = "Synthetic viewer became the No. 72 fan in the Fan Club") {
  const notice = el("div", {}, [el("div", {}, [el("svg")]), el("div", {}, [text])]);
  el("div", {"data-index": "25"}, [notice]);
  return notice;
}
function giftRow({name = "Synthetic sender", gift = "Heart Me", quantity = "1", badges = false} = {}) {
  const owner = el("div", {"data-e2e": "message-owner-name", title: name}, [name]);
  const badge = value => el("span", {}, [el("img", {src: "https://invalid.test/badge"}), el("span", {}, [value])]);
  const header = el("div", {}, badges ? [badge("18"), badge("TEST"), owner, badge("No. 2")] : [owner]);
  const body = el("div", {}, [header, " sent ", el("span", {}, [gift]),
    el("span", {}, [el("img", {src: "https://invalid.test/gift"})]), " × ", quantity]);
  const notice = el("div", {}, [el("div", {}, [el("svg")]), body]);
  el("div", {"data-index": "31"}, [notice]);
  return notice;
}
const entry = node => ({node, parsed: core.parseRow(node)});
function recorder(options = {}) { return new core.Recorder({room: "tiktok:@test_creator", sessionId: "session-a", now: () => 10000, ...options}); }

test("scope is restricted to explicit HTTPS TikTok LIVE rooms, not arbitrary URLs", () => {
  assert.equal(core.roomFromUrl("https://www.tiktok.com/@Test_Creator/live?source=public"), "tiktok:@test_creator");
  assert.equal(core.roomFromUrl("https://tiktok.com/@creator/live/"), "tiktok:@creator");
  for (const url of ["http://www.tiktok.com/@creator/live", "https://www.tiktok.com.evil.test/@creator/live", "https://www.tiktok.com:9040/@creator/live", "https://www.tiktok.com/live", "https://www.tiktok.com/@creator", "https://name:secret@www.tiktok.com/@creator/live", "https://evil.test/?next=https://www.tiktok.com/@creator/live", "not a URL"]) assert.equal(core.roomFromUrl(url), null);
});
test("chat parsing separates badge/owner from content and does not invent IDs", () => {
  const parsed = core.parseRow(row());
  assert.equal(parsed.type, "chat.message"); assert.equal(parsed.text, "Hello");
  assert.deepEqual(parsed.actor, {id: null, handle: null, display_name: "Test Viewer", identity_quality: "display-name-only"});
});
test("join is an observed notice, not first chat; unsupported labels fail closed", () => {
  assert.equal(core.parseRow(row({marker: "enter-message", text: "joined"})).type, "viewer.join.observed");
  assert.equal(core.parseRow(row({text: "joined"})).type, "chat.message");
  assert.equal(core.parseRow(row({marker: "enter-message", text: "followed"})).error, "unmapped-enter-notice");
  assert.equal(core.parseRow(row({marker: "unknown-event", text: "sent a gift"})).error, "unmapped-label");
});
test("changed layout and missing owners cannot produce bogus chat", () => {
  const missing = row(); missing.children[1].children[0].childNodes = [];
  assert.equal(core.parseRow(missing).error, "owner-shape-changed");
  const changed = row(); changed.children[1].childNodes.push(el("button", {}, ["Report"]));
  assert.equal(core.parseRow(changed).error, "content-shape-changed");
  assert.equal(core.parseRow(row({name: ""})).error, "missing-display-name");
  assert.equal(core.parseRow(row({text: ""})).error, "empty-content");
});

test("follow labels require the observed nested structure and exact notice, not chat keywords", () => {
  const parsed = core.parseRow(followRow());
  assert.equal(parsed.type, "viewer.follow.observed"); assert.equal(parsed.text, null);
  assert.equal(parsed.actor.display_name, "Synthetic follower"); assert.equal(parsed.actor.id, null);
  assert.equal(core.parseRow(row({text: "followed the host"})).type, "chat.message");
  assert.equal(core.parseRow(followRow("shared the LIVE")).error, "unmapped-social-notice");
  assert.equal(core.parseRow(row({marker: "social-message", text: "followed the host"})).error, "social-shape-changed");
});

test("Fan Club prose remains an unattributed notice, never a paid fan or a contribution", () => {
  const parsed = core.parseRow(fanRow());
  assert.equal(parsed.type, "viewer.fan_club_notice.observed"); assert.equal(parsed.provider_label, null);
  assert.deepEqual(parsed.actor, {id: null, handle: null, display_name: null, identity_quality: "unattributed"});
  const record = recorder(); const [event] = record.ingest([entry(fanRow())]);
  assert.equal(event.provider_event_id, null); assert.equal(event.eligible_for_contributions, false);
  assert.equal(record.report().events[0].text, "[redacted]");
  assert.equal(record.report().events[0].actor.display_name, null);
  assert.equal(record.report().capabilities.super_fans, "unverified");
});

test("unlabelled notices fail closed on changed wording, DOM shape, or missing list wrapper", () => {
  for (const text of ["became the No. 72 fan in the Fan Club", "Synthetic viewer became a Super Fan", "Synthetic viewer sent Heart Me × 1", "Synthetic viewer became the No. 0 fan in the Fan Club"]) {
    assert.ok(core.parseRow(fanRow(text)).error);
  }
  const missingWrapper = fanRow(); missingWrapper.parentElement = null;
  assert.ok(core.parseRow(missingWrapper).error);
  const richBody = fanRow(); richBody.children[1].childNodes.push(el("span", {}, ["extra"]));
  assert.ok(core.parseRow(richBody).error);
  assert.equal(core.parseRow(row({text: fanRow().children[1].textContent})).type, "chat.message");
});

test("inspected gift structure separates badges, owner, gift name and displayed quantity", () => {
  for (const [gift, quantity, badges] of [["Heart Me", "1", false], ["Treasure Clover", "2", true], ["GOAT", "1", true]]) {
    const parsed = core.parseRow(giftRow({gift, quantity, badges}));
    assert.equal(parsed.type, "gift.notice.observed"); assert.equal(parsed.text, null);
    assert.equal(parsed.actor.display_name, "Synthetic sender");
    assert.deepEqual(parsed.gift, {name: gift, id: null, displayed_quantity: Number(quantity), quantity_semantics: "unknown",
      streak_id: null, streak_complete: null, coin_value: null});
    assert.equal(JSON.stringify(parsed).includes("https:"), false);
  }
});

test("native SVG casing is accepted; chat gift claims and plain-text imitations are not gifts", () => {
  const node = giftRow(); node.children[0].children[0].tagName = "svg";
  assert.equal(core.parseRow(node).type, "gift.notice.observed");
  assert.equal(core.parseRow(row({text: "Synthetic sender sent Heart Me × 1"})).type, "chat.message");
  assert.ok(core.parseRow(fanRow("Synthetic sender sent Heart Me × 1")).error);
});

test("gift quantities reject zero, negative, decimals, coercion and overlong numbers", () => {
  for (const quantity of ["", "0", "-1", "+1", "01", "1.5", "1e3", "Infinity", "NaN", "1,000", "1 gift", "١", "1000000000", "9".repeat(10000)]) {
    assert.equal(core.parseRow(giftRow({quantity})).error, "unmapped-gift-value", quantity.slice(0, 30));
  }
  assert.equal(core.parseRow(giftRow({quantity: "999999999"})).gift.displayed_quantity, 999999999);
});

test("gift parser fails closed on owner, icon, locale, list and content drift", () => {
  const mutations = [
    node => { node.parentElement = null; },
    node => { node.children[0].childNodes = []; },
    node => { node.children[1].children[0].childNodes = []; },
    node => { node.children[1].children[0].childNodes.push(el("div", {"data-e2e": "message-owner-name"}, ["Other"])); },
    node => { node.children[1].children[1].childNodes.push(el("img", {alt: "fake"})); },
    node => { node.children[1].children[2].childNodes = []; },
    node => { node.children[1].childNodes[1].textContent = " shared "; },
    node => { node.children[1].childNodes[4].textContent = " x "; },
    node => { node.children[1].childNodes[5] = el("span", {}, ["1"]); },
    node => { node.children[1].childNodes.push(el("button", {}, ["Send"])); }
  ];
  for (const mutate of mutations) { const node = giftRow(); mutate(node); assert.ok(core.parseRow(node).error); }
  assert.equal(core.parseRow(giftRow({name: ""})).error, "missing-display-name");
});

test("gift labels are bounded plain text and sender truncation remains explicit", () => {
  for (const gift of ["", " ", "X".repeat(161)]) assert.equal(core.parseRow(giftRow({gift})).error, "unmapped-gift-value");
  const parsed = core.parseRow(giftRow({name: "N".repeat(150), gift: "<b>Gift ✨</b>"}));
  assert.equal(parsed.gift.name, "<b>Gift ✨</b>"); assert.equal(parsed.actor.display_name.length, 128); assert.equal(parsed.truncated, true);
});

test("gift redraws and quantity updates are observations, never summed transactions", () => {
  const record = recorder(), node = giftRow();
  record.ingest([entry(node)], {baseline: true});
  assert.equal(record.ingest([entry(node)]).length, 0);
  node.children[1].childNodes[5].textContent = "2";
  const [update] = record.ingest([entry(node)]);
  assert.equal(update.gift.displayed_quantity, 2); assert.equal(update.gift.quantity_semantics, "unknown");
  assert.equal(record.ingest([entry(giftRow({quantity: "2"}))]).length, 0);
  node.children[1].childNodes[5].textContent = "3"; record.ingest([entry(node)]);
  assert.equal(record.counters.observed, 2); assert.equal(record.counters.ambiguous_repeats_skipped, 1);
  for (const event of record.report(true).events) {
    assert.equal(event.provider_event_id, null); assert.equal(event.actor.id, null); assert.equal(event.actor.handle, null);
    assert.equal(event.eligible_for_actions, false); assert.equal(event.eligible_for_contributions, false);
    assert.equal(event.gift.streak_id, null); assert.equal(event.gift.streak_complete, null); assert.equal(event.gift.coin_value, null);
  }
});

test("gift export redacts sender names and clones gift metadata without exposing asset URLs", () => {
  const record = recorder(); record.ingest([entry(giftRow())]); const report = record.report();
  assert.equal(report.events[0].actor.display_name, "[redacted]"); assert.equal(report.events[0].text, null);
  assert.equal(report.events[0].gift.name, "Heart Me");
  report.events[0].gift.displayed_quantity = 999;
  assert.equal(record.report(true).events[0].gift.displayed_quantity, 1);
  assert.equal(record.report(true).events[0].actor.display_name, "Synthetic sender");
  assert.equal(JSON.stringify(record.report(true)).includes("https:"), false);
  assert.ok(report.limitations.some(text => text.includes("never additive")));
});
test("chat is plain text, bounded, and image alt text does not import remote assets", () => {
  const parsed = core.parseRow(row({text: "<script>alert(1)</script>", extra: [el("img", {alt: "[smile]", src: "https://invalid.test/emote"}), el("script", {}, ["bad code"])]}));
  assert.equal(parsed.text, "<script>alert(1)</script>[smile]");
  assert.equal(JSON.stringify(parsed).includes("https:"), false);
  const large = core.parseRow(row({name: "N".repeat(150), text: "A".repeat(5000)}));
  assert.equal(large.text.length, 4096); assert.equal(large.actor.display_name.length, 128); assert.equal(large.truncated, true);
});
test("existing visible history is baselined and same-node repaints do not emit", () => {
  const record = recorder(), node = row();
  assert.equal(record.ingest([entry(node)], {baseline: true}).length, 0);
  assert.equal(record.ingest([entry(node)]).length, 0);
  assert.equal(record.counters.initial_rows_skipped, 1); assert.equal(record.counters.redraws_skipped, 1);
  assert.equal(record.ingest([entry(row({text: "New"}))]).length, 1);
});
test("cloned repeated rows are suppressed conservatively with an explicit ambiguity count", () => {
  const record = recorder();
  assert.equal(record.ingest([entry(row())]).length, 1);
  assert.equal(record.ingest([entry(row())]).length, 0);
  assert.equal(record.counters.ambiguous_repeats_skipped, 1);
});
test("recycled DOM nodes can deliver new content; identical later comments remain possible", () => {
  let time = 10000; const record = recorder({now: () => time}), node = row();
  record.ingest([entry(node)]);
  node.children[1].children[1].childNodes = [{nodeType: 3, textContent: "Changed"}];
  assert.equal(record.ingest([entry(node)]).length, 1);
  time += 6000;
  assert.equal(record.ingest([entry(row())]).length, 1);
});
test("observations are off-air and not trusted contribution/giveaway inputs", () => {
  const [event] = recorder().ingest([entry(row())]);
  assert.equal(event.observation_id, "session-a:1"); assert.equal(event.provider_event_id, null);
  assert.equal(event.occurred_at, null); assert.equal(event.eligible_for_actions, false);
  assert.equal(event.eligible_for_contributions, false); assert.equal(event.source.deduplication, "best-effort");
});
test("bounded buffer evicts oldest rows without silently losing the eviction count", () => {
  const record = recorder({capacity: 2});
  for (let i = 0; i < 4; i++) record.ingest([entry(row({text: `Message ${i}`}))]);
  assert.equal(record.events.length, 2); assert.equal(record.counters.evicted_records, 2);
  assert.equal(record.counters.observed, 4); assert.equal(record.events[0].text, "Message 2");
});
test("default diagnostic exports redact names and chat; explicit text export does not mutate buffer", () => {
  const record = recorder(); record.ingest([entry(row())]); record.coverageGap();
  const report = record.report();
  assert.equal(report.events[0].actor.display_name, "[redacted]"); assert.equal(report.events[0].text, "[redacted]");
  assert.equal(report.counters.coverage_gaps, 1); assert.equal(report.off_air, true);
  assert.equal(record.report(true).events[0].text, "Hello");
});
test("missing metrics stay unverified and malformed rows do not enter the ledger", () => {
  const record = recorder(); record.ingest([entry(row({marker: "unknown"}))]);
  assert.equal(record.events.length, 0); assert.equal(record.counters.malformed_rows, 1);
  assert.equal(record.report().capabilities.gifts, "observed-public-dom-notices-only");
  assert.equal(record.report().capabilities.gift_quantity_semantics, "unverified");
  assert.equal(record.report().capabilities.gift_streak_completion, "unverified");
  assert.equal(record.report().capabilities.production_actions, "disabled");
});
test("invalid buffer limits are rejected", () => {
  for (const capacity of [0, -1, 501, 1.5, Infinity]) assert.throws(() => recorder({capacity}));
});

function runtime() {
  const root = {isConnected: true, rows: [row()], querySelectorAll() { return this.rows; }};
  const intervals = new Map(), timeouts = new Map(); let nextTimer = 0, listener, mutation;
  const context = vm.createContext({window: {RareIQLabelProbeCore: core, addEventListener() {}},
    location: {href: "https://www.tiktok.com/@test_creator/live"},
    document: {currentRoot: root, querySelector() { return this.currentRoot; }},
    crypto: {randomUUID: () => "test-session"},
    chrome: {runtime: {id: "test-extension", onMessage: {addListener(value) { listener = value; }}}},
    MutationObserver: class {constructor(callback) { mutation = callback; } observe() {} disconnect() {}},
    setInterval(fn) { intervals.set(++nextTimer, fn); return nextTimer; }, clearInterval(id) { intervals.delete(id); },
    setTimeout(fn) { timeouts.set(++nextTimer, fn); return nextTimer; }, clearTimeout(id) { timeouts.delete(id); }
  });
  vm.runInContext(fs.readFileSync(path.join(folder, "content.js"), "utf8"), context);
  return {root, context, intervals,
    command(command, sender = "test-extension", extra = {}) { let result; listener({channel: "rareiq-label-probe", command, ...extra}, {id: sender}, value => { result = value; }); return result; },
    mutate() { mutation(); for (const [id, fn] of [...timeouts]) { timeouts.delete(id); fn(); } },
    tick() { for (const fn of [...intervals.values()]) fn(); }
  };
}
test("runtime does not start automatically; only its own extension can issue commands", () => {
  const app = runtime(); assert.equal(app.intervals.size, 0);
  assert.equal(app.command("start", "another-extension"), undefined); assert.equal(app.intervals.size, 0);
  assert.equal(app.command("status").state, "stopped");
});
test("runtime start baselines history, observes new rows and stop disconnects", () => {
  const app = runtime(); assert.equal(app.command("start").buffered, 0);
  app.root.rows.push(row({text: "A new chat"})); app.mutate();
  assert.equal(app.command("status").buffered, 1);
  app.command("stop"); assert.equal(app.intervals.size, 0); assert.equal(app.command("status").state, "stopped");
  app.command("clear"); assert.equal(app.command("export").report, null);
});

test("runtime exports gift quantity mutations but never activates contributions", () => {
  const app = runtime(); app.command("start"); const node = giftRow();
  app.root.rows.push(node); app.mutate(); node.children[1].childNodes[5].textContent = "2"; app.mutate();
  const {report} = app.command("export");
  assert.deepEqual(report.events.map(event => event.gift.displayed_quantity), [1, 2]);
  assert.ok(report.events.every(event => event.eligible_for_contributions === false));
  app.command("stop"); assert.equal(app.intervals.size, 0);
});
test("SPA room navigation stops collection instead of following arbitrary creators", () => {
  const app = runtime(); app.command("start");
  app.context.location.href = "https://www.tiktok.com/@different_creator/live"; app.tick();
  assert.equal(app.command("status").state, "stopped"); assert.equal(app.intervals.size, 0);
});

test("commands validate room immediately, including navigation before the next interval tick", () => {
  const app = runtime(); app.command("start");
  app.context.location.href = "https://www.tiktok.com/@different_creator/live";
  assert.equal(app.command("status").state, "stopped");
  assert.equal(app.command("start", "test-extension", {room: "tiktok:@test_creator"}).ok, false);
  const result = app.command("start", "test-extension", {room: "tiktok:@different_creator"});
  assert.equal(result.room, "tiktok:@different_creator"); assert.equal(result.state, "observing");
});

test("an extension version mismatch blocks Start but never blocks emergency Stop/Clear", () => {
  const app = runtime(); app.command("start");
  assert.equal(app.command("start", "test-extension", {version: "future"}).ok, false);
  assert.equal(app.command("stop", "test-extension", {version: "future"}).state, "stopped");
  assert.equal(app.command("clear", "test-extension", {version: "future"}).room, null);
});
test("chat remount is recorded as a coverage gap and new history is not replayed", () => {
  const app = runtime(); app.command("start"); app.root.isConnected = false;
  app.context.document.currentRoot = null; app.tick();
  assert.equal(app.command("status").state, "waiting");
  app.context.document.currentRoot = {isConnected: true, querySelectorAll: () => [row({text: "Remounted history"})]}; app.tick();
  const state = app.command("status"); assert.equal(state.state, "observing"); assert.equal(state.buffered, 0);
  assert.equal(state.counters.coverage_gaps, 1);
});
test("oversized DOM stops rather than starting an unbounded observer loop", () => {
  const app = runtime(); app.root.rows = Array.from({length: 251}, () => row());
  assert.equal(app.command("start").state, "stopped"); assert.equal(app.intervals.size, 0);
});
test("extension permissions exclude persistent hosts, cookies, storage and network interception", () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(folder, "manifest.json")));
  assert.equal(manifest.version, core.VERSION);
  assert.deepEqual(manifest.permissions, ["activeTab", "scripting"]);
  for (const key of ["host_permissions", "content_scripts", "externally_connectable", "background"]) assert.equal(manifest[key], undefined);
  for (const file of ["core.js", "content.js", "popup.js"]) {
    const source = fs.readFileSync(path.join(folder, file), "utf8");
    assert.doesNotMatch(source, /\bfetch\s*\(|\bWebSocket\s*\(|\bXMLHttpRequest\b|document\.cookie|localStorage|sessionStorage|innerHTML\s*=|\beval\s*\(/);
  }
});
test("all probe scripts parse and popup/test assets resolve locally", () => {
  for (const file of fs.readdirSync(folder).filter(file => file.endsWith(".js"))) {
    assert.doesNotThrow(() => new vm.Script(fs.readFileSync(path.join(folder, file), "utf8"), {filename: file}));
  }
  for (const file of ["popup.html", "self_test.html"]) {
    const html = fs.readFileSync(path.join(folder, file), "utf8");
    for (const match of html.matchAll(/(?:src|href)="([^"]+)"/g)) assert.ok(fs.existsSync(path.join(folder, match[1])), match[1]);
  }
});

const settled = () => new Promise(resolve => setImmediate(resolve));
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return {promise, resolve, reject}; }
function reply(state = "stopped", extra = {}) { return {ok: true, version: core.VERSION, state, reason: "Synthetic test", counters: {}, buffered: 0, ...extra}; }
function popup({query, sendMessage, executeScript, extensionAvailable = true} = {}) {
  const elements = new Map(), timers = new Map(), intervals = new Map(), calls = [], listeners = {}, downloads = [];
  let id = 0;
  function element(name) {
    if (!elements.has(name)) elements.set(name, {textContent: "", checked: false, listeners: {},
      addEventListener(event, handler) { this.listeners[event] = handler; }, click() { return this.listeners.click?.(); }});
    return elements.get(name);
  }
  const context = vm.createContext({window: {RareIQLabelProbeCore: core, addEventListener(event, handler) { listeners[event] = handler; }},
    document: {getElementById: element, createElement() { return {click() { downloads.push(this.download); }}; }},
    chrome: extensionAvailable ? {
      tabs: {query: query || (async () => [{id: 7, url: "https://www.tiktok.com/@test_creator/live"}]),
        sendMessage(tabId, message) { calls.push({tabId, ...message}); return (sendMessage || (async () => reply()))(tabId, message); }},
      scripting: {executeScript: executeScript || (async () => [])}
    } : undefined, Blob, URL: {createObjectURL: () => "blob:local-test", revokeObjectURL() {}},
    setTimeout(fn, ms) { timers.set(++id, {fn, ms}); return id; }, clearTimeout(key) { timers.delete(key); },
    setInterval(fn) { intervals.set(++id, fn); return id; }, clearInterval(key) { intervals.delete(key); }
  });
  vm.runInContext(fs.readFileSync(path.join(folder, "popup.js"), "utf8"), context);
  return {element, calls, downloads, timers,
    click: name => element(name).click(), tick() { for (const fn of intervals.values()) fn(); },
    expire() { for (const [key, timer] of [...timers]) if (timer.ms === 4000) { timers.delete(key); timer.fn(); } },
    close() { listeners.pagehide(); }, context};
}

test("popup injects only after an explicit Start, then reaches the content command handler", async () => {
  let app, injections = 0;
  const ui = popup({sendMessage: async (_, message) => {
    if (!app) throw new Error("Could not establish connection. Receiving end does not exist.");
    return app.command(message.command, "test-extension", message);
  }, executeScript: async args => {
    assert.equal(args.target.tabId, 7); assert.deepEqual(Array.from(args.files), ["core.js", "content.js"]);
    injections++; app = runtime();
  }});
  await settled(); assert.equal(injections, 0);
  await ui.click("start"); assert.equal(injections, 1); assert.equal(ui.element("status").textContent, "Observing · off air");
  assert.equal(app.command("status").buffered, 0);
  await ui.click("stop"); assert.equal(app.command("status").state, "stopped");
  await ui.click("clear"); assert.equal(app.command("export").report, null);
});

test("Stop is not dropped by an in-flight status refresh and stale replies cannot repaint it", async () => {
  const oldStatus = deferred();
  const ui = popup({sendMessage: async (_, message) => message.command === "status" ? oldStatus.promise : reply()});
  await settled(); await ui.click("stop");
  assert.ok(ui.calls.some(call => call.command === "stop")); assert.equal(ui.element("status").textContent, "Stopped");
  oldStatus.resolve(reply("observing")); await settled();
  assert.equal(ui.element("status").textContent, "Stopped");
});

test("Stop during injection prevents the pending Start from firing when injection finishes", async () => {
  const injection = deferred(); let injected = false;
  const ui = popup({sendMessage: async (_, message) => {
    if (message.command === "start") throw new Error("Receiving end does not exist");
    return reply();
  }, executeScript: () => { injected = true; return injection.promise; }});
  await settled(); const starting = ui.click("start"); await settled(); assert.equal(injected, true);
  await ui.click("stop"); injection.resolve([]); await starting;
  assert.equal(ui.calls.filter(call => call.command === "start").length, 1);
  assert.equal(ui.element("status").textContent, "Stopped");
});

test("Stop and Clear supersede a delayed Start response and keep controls available", async () => {
  const start = deferred();
  const ui = popup({sendMessage: async (_, message) => message.command === "start" ? start.promise : reply()});
  await settled(); const starting = ui.click("start"); await settled();
  await ui.click("stop"); await ui.click("clear"); start.resolve(reply("observing")); await starting;
  assert.deepEqual(ui.calls.map(call => call.command), ["status", "start", "stop", "clear"]);
  assert.equal(ui.element("status").textContent, "Stopped");
});

test("transport timeout reports unknown state, never reinjects or disables Stop", async () => {
  let injections = 0;
  const ui = popup({sendMessage: async (_, message) => message.command === "start" ? new Promise(() => {}) : reply(),
    executeScript: async () => { injections++; }});
  await settled(); const starting = ui.click("start"); await settled(); ui.expire(); await starting;
  assert.equal(ui.element("status").textContent, "Connection unconfirmed"); assert.match(ui.element("detail").textContent, /unknown/);
  assert.equal(injections, 0); await ui.click("stop"); assert.equal(ui.element("status").textContent, "Stopped");
});

test("failed polling clears a stale Observing status instead of hiding disconnects", async () => {
  let connected = true;
  const ui = popup({sendMessage: async () => { if (!connected) throw new Error("Tab closed"); return reply("observing"); }});
  await settled(); assert.equal(ui.element("status").textContent, "Observing · off air");
  connected = false; ui.tick(); await settled(); assert.equal(ui.element("status").textContent, "Connection unconfirmed");
});

test("permission errors do not trigger injection and wrong-page tabs cannot start", async () => {
  let injections = 0;
  const ui = popup({sendMessage: async () => { throw new Error("Cannot access contents of the page"); }, executeScript: async () => { injections++; }});
  await settled(); await ui.click("start"); assert.equal(injections, 0);
  assert.match(ui.element("detail").textContent, /Cannot access/);
  const wrong = popup({query: async () => [{id: 9, url: "https://example.test"}]});
  await settled(); await wrong.click("start"); assert.equal(wrong.calls.length, 0);
});

test("popup pins its target tab and room, and version mismatches leave Stop usable", async () => {
  let queries = 0;
  const ui = popup({query: async () => { queries++; return [{id: queries === 1 ? 7 : 9, url: "https://www.tiktok.com/@test_creator/live"}]; },
    sendMessage: async (_, message) => reply(message.command === "stop" ? "stopped" : "observing", {version: "old"})});
  await settled(); assert.match(ui.element("detail").textContent, /reload/);
  await ui.click("stop"); assert.equal(ui.element("status").textContent, "Stopped"); assert.equal(queries, 1);
  assert.ok(ui.calls.every(call => call.tabId === 7 && call.room === "tiktok:@test_creator"));
});

test("closing the popup during injection cancels an unconfirmed Start", async () => {
  const injection = deferred();
  const ui = popup({sendMessage: async (_, message) => { if (message.command === "start") throw new Error("Receiving end does not exist"); return reply(); },
    executeScript: () => injection.promise});
  await settled(); const starting = ui.click("start"); await settled(); ui.close(); injection.resolve([]); await starting;
  assert.equal(ui.calls.filter(call => call.command === "start").length, 1);
});

test("ordinary browser preview is explicitly disconnected and its controls are disabled", () => {
  const ui = popup({extensionAvailable: false});
  assert.equal(ui.element("status").textContent, "Preview only · not connected");
  assert.equal(ui.element("start").disabled, true); assert.equal(ui.element("includeText").disabled, true);
  assert.equal(ui.calls.length, 0);
});
