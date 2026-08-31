const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const staticRoot = path.resolve(__dirname, "../../rareiq/web/static");
const settle = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };

function element() {
  const classes = new Set();
  return {
    textContent: "", innerHTML: "", hidden: false, src: "", dataset: {}, children: [],
    style: {setProperty() {}}, offsetWidth: 100,
    classList: {
      add(...names) { names.forEach(name => classes.add(name)); },
      remove(...names) { names.forEach(name => classes.delete(name)); },
      toggle(name, enabled) { if (enabled) classes.add(name); else classes.delete(name); },
      contains(name) { return classes.has(name); },
    },
    removeAttribute(name) { delete this[name]; },
    replaceChildren(...children) { this.children = children; },
  };
}

async function browser(file, request) {
  let now = 1000000, nextTimer = 0;
  const timers = new Map(), elements = new Map(), listeners = new Map();
  const get = id => {
    if (!elements.has(id)) elements.set(id, element());
    return elements.get(id);
  };
  const schedule = (fn, delay = 0, repeat = false) => {
    const id = ++nextTimer;
    timers.set(id, {fn, time: now + delay, delay, repeat});
    return id;
  };
  const context = vm.createContext({
    document: {getElementById: get, createElement: element, documentElement: element(), body: element()},
    location: {search: "", origin: "http://127.0.0.1:9040"},
    Date: {now: () => now}, URLSearchParams, AbortController, console,
    setTimeout: (fn, delay) => schedule(fn, delay), clearTimeout: id => timers.delete(id),
    setInterval: (fn, delay) => schedule(fn, delay, true), clearInterval: id => timers.delete(id),
    fetch: async (url, options) => {
      const payload = await request(url, options);
      return {ok: payload?.httpOk !== false, json: async () => payload};
    },
    addEventListener: (name, handler) => listeners.set(name, handler),
  });
  context.window = context;
  context.parent = context;
  const html = fs.readFileSync(path.join(staticRoot, file), "utf8");
  for (const match of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)) {
    const src = /src="\/static\/([^"]+)"/.exec(match[1]);
    const source = src ? fs.readFileSync(path.join(staticRoot, src[1].split("?")[0]), "utf8") : match[2];
    vm.runInContext(source, context, {filename: src?.[1] || file});
  }
  await settle();
  return {
    get, context, timers, listeners,
    async advance(ms) {
      const target = now + ms;
      for (;;) {
        const next = [...timers].filter(([, timer]) => timer.time <= target).sort((a, b) => a[1].time - b[1].time)[0];
        if (!next) break;
        const [id, timer] = next;
        now = timer.time;
        timers.delete(id);
        if (timer.repeat) timers.set(id, {...timer, time: now + timer.delay});
        timer.fn();
        await settle();
      }
      now = target;
      await settle();
    },
  };
}

const profile = () => ({
  ok: true, on_air: true, identity: {card_id: "card-a", verified: true},
  pokemon: {id: 827, name: "Nickit", flavor_text: "Initial profile", types: ["Dark"], abilities: ["Run Away"]},
});

function replayState(overrides = {}) {
  return {ok: true, highlights: [{id: "clip-a", frames: 50, fps: 5}],
    playback: {active: true, generation: 1, highlight_id: "clip-a", speed: 1, started_at: 1000, ...overrides}};
}

test("replay reload resumes at the current frame instead of restarting the clip", async () => {
  const page = await browser("overlay_replay.html", () => replayState({started_at: 996}));
  assert.match(page.get("frame").src, /\/frame\/20\?/);
  page.get("frame").onload?.();
  assert.equal(page.get("replay").classList.contains("active"), true);
});

test("expired replay stays hidden when the browser source reloads", async () => {
  const page = await browser("overlay_replay.html", () => replayState({started_at: 980}));
  assert.equal(page.get("replay").classList.contains("active"), false);
  assert.ok(!page.get("frame").src);
});

test("replay failure hides stale frames and same-generation recovery uses current time", async () => {
  let failed = false;
  const page = await browser("overlay_replay.html", () => ({...replayState(), httpOk: !failed}));
  page.get("frame").onload?.();
  failed = true;
  await page.advance(250);
  assert.equal(page.get("replay").classList.contains("active"), false);
  assert.ok(!page.get("frame").src);
  failed = false;
  await page.advance(750);
  assert.match(page.get("frame").src, /\/frame\/5\?/);
  page.get("frame").onload?.();
  assert.equal(page.get("replay").classList.contains("active"), true);
});

test("Return To Live invalidates late replay image callbacks without a generation change", async () => {
  let state = replayState();
  const page = await browser("overlay_replay.html", () => state);
  const oldLoad = page.get("frame").onload;
  state = replayState({active: false});
  await page.advance(250);
  oldLoad?.();
  assert.equal(page.get("replay").classList.contains("active"), false);
});

test("replay frame errors hide the output instead of leaving a broken image on air", async () => {
  const page = await browser("overlay_replay.html", () => replayState());
  page.get("frame").onload?.();
  page.get("frame").onerror?.();
  assert.equal(page.get("replay").classList.contains("active"), false);
});

test("replay image and polling timers are released on pagehide", async () => {
  const page = await browser("overlay_replay.html", () => replayState());
  page.get("frame").onload?.();
  page.listeners.get("pagehide")?.();
  await settle();
  assert.equal(page.get("replay").classList.contains("active"), false);
  assert.equal(page.timers.size, 0);
});

test("card safety withdrawal hides graphics even without a new animation generation", async () => {
  let graphic = {generation: 4, visible: true, kind: "card", title: "Card A"};
  const page = await browser("overlay_graphics.html", () => ({ok: true, graphic}));
  assert.equal(page.get("graphic").classList.contains("visible"), true);
  graphic = {...graphic, visible: false, safety_status: "blocked"};
  await page.advance(250);
  assert.equal(page.get("graphic").classList.contains("visible"), false);
});

test("graphics hide on HTTP failure and recover without a new generation", async () => {
  let failed = false;
  const graphic = {generation: 4, visible: true, title: "Guest"};
  const page = await browser("overlay_graphics.html", () => ({httpOk: !failed, graphic}));
  failed = true;
  await page.advance(250);
  assert.equal(page.get("graphic").classList.contains("visible"), false);
  failed = false;
  await page.advance(250);
  assert.equal(page.get("graphic").classList.contains("visible"), true);
});

test("expired graphics do not replay when a browser source reloads", async () => {
  const page = await browser("overlay_graphics.html", () => ({graphic: {
    generation: 4, visible: true, title: "Expired", shown_at: 990, duration_ms: 1000,
  }}));
  assert.equal(page.get("graphic").classList.contains("visible"), false);
});

test("an active timed graphic expires once and does not reappear on the next poll", async () => {
  const page = await browser("overlay_graphics.html", () => ({graphic: {
    generation: 4, visible: true, title: "Brief", shown_at: 1000, duration_ms: 500,
  }}));
  assert.equal(page.get("graphic").classList.contains("visible"), true);
  await page.advance(750);
  assert.equal(page.get("graphic").classList.contains("visible"), false);
});

test("Rare Intelligence updates same-card profile content", async () => {
  let payload = profile();
  const page = await browser("overlay_pokedex.html", url => url.includes("/current") ? payload : {state: {}});
  payload = {...payload, pokemon: {...payload.pokemon, flavor_text: "Refreshed profile"}};
  await page.advance(750);
  assert.equal(page.get("flavor").textContent, "Refreshed profile");
});

test("Rare Intelligence obeys On Air changes without changing cards", async () => {
  let payload = profile();
  const page = await browser("overlay_pokedex.html", url => url.includes("/current") ? payload : {state: {}});
  assert.equal(page.get("stage").classList.contains("live"), true);
  payload = {...payload, on_air: false};
  await page.advance(750);
  assert.equal(page.get("stage").classList.contains("live"), false);
});

test("Rare Intelligence hides on non-success HTTP responses", async () => {
  const page = await browser("overlay_pokedex.html", url => url.includes("/current") ? {...profile(), httpOk: false} : {state: {}});
  assert.equal(page.get("stage").classList.contains("live"), false);
});

test("slow profile requests are single-flight, time out, and ignore late results", async () => {
  let calls = 0, release;
  const page = await browser("overlay_pokedex.html", url => {
    if (!url.includes("/current")) return {state: {}};
    calls++;
    return new Promise(resolve => { release = resolve; });
  });
  await page.advance(1500);
  assert.equal(calls, 1);
  await page.advance(2500);
  release(profile());
  await settle();
  assert.equal(page.get("stage").classList.contains("live"), false);
  await page.advance(750);
  assert.equal(calls, 2);
});

for (const template of ["overlay_current_card.html", "overlay_landscape.html", "overlay_portrait.html"]) {
test(`${template} clears stale card details on disconnect`, async () => {
  let disconnected = false;
  const page = await browser(template, url => {
    if (disconnected) throw new Error("offline");
    return url === "/api/brand" ? {brand: {}} : {state: {current_card_status: "verified", current_card: {card_name: "Card A"}}};
  });
  assert.equal(page.get("cardName").textContent, "Card A");
  disconnected = true;
  await page.advance(750);
  assert.notEqual(page.get("cardName").textContent, "Card A");
});
}

test("a stalled refresh hides an already-live Rare Intelligence profile at the deadline", async () => {
  let stalled = false;
  const page = await browser("overlay_pokedex.html", url => {
    if (!url.includes("/current")) return {state: {}};
    return stalled ? new Promise(() => {}) : profile();
  });
  assert.equal(page.get("stage").classList.contains("live"), true);
  stalled = true;
  await page.advance(750 + 4000);
  assert.equal(page.get("stage").classList.contains("live"), false);
});

test("production screen visibility follows state even with unchanged generation", async () => {
  let screen = {generation: 7, visible: true, title: "Break"};
  const page = await browser("overlay_production_screen.html", () => ({screen}));
  screen = {...screen, visible: false};
  await page.advance(250);
  assert.equal(page.get("screen").classList.contains("visible"), false);
});

test("production screen hides on connection loss and recovers with current countdown", async () => {
  let disconnected = false;
  const page = await browser("overlay_production_screen.html", () => {
    if (disconnected) throw new Error("offline");
    return {screen: {generation: 7, visible: true, countdown_seconds: 30, started_at: 1000}};
  });
  assert.equal(page.get("countdown").textContent, "00:30");
  disconnected = true;
  await page.advance(250);
  assert.equal(page.get("screen").classList.contains("visible"), false);
  await page.advance(1000);
  disconnected = false;
  await page.advance(250);
  assert.equal(page.get("screen").classList.contains("visible"), true);
  assert.equal(page.get("countdown").textContent, "00:29");
});

test("pagehide stops polling and hides the overlay", async () => {
  const page = await browser("overlay_pokedex.html", url => url.includes("/current") ? profile() : {state: {}});
  assert.equal(typeof page.listeners.get("pagehide"), "function");
  page.listeners.get("pagehide")();
  await settle();
  assert.equal(page.timers.size, 0);
  assert.equal(page.get("stage").classList.contains("live"), false);
});
