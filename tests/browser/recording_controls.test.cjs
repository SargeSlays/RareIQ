const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.resolve(__dirname, "../../rareiq/web/static/studiox.js"), "utf8");
function functionsBetween(first, next) {
  const start = source.indexOf(first), end = source.indexOf(next, start);
  assert.ok(start >= 0 && end > start);
  return source.slice(start, end);
}
function app(code, api) {
  const nodes = new Map(), notices = [];
  const context = vm.createContext({$: id => nodes.get(id) || null, api, notify: (...args) => notices.push(args), console});
  vm.runInContext(code, context);
  return {context, notices, mount(id, props = {}) { const node = {disabled: false, textContent: "", value: "", ...props}; nodes.set(id, node); return node; }};
}

test("recording controls show failures and saved output instead of always saying ready", () => {
  const ui = app(functionsBetween("function recordingStatusText(", "function renderProductionSession("));
  assert.match(ui.context.recordingStatusText({configured: true, last_error: "Encoder exited with code 7"}), /code 7/);
  assert.match(ui.context.recordingStatusText({configured: true, verified: true}), /saved/i);
  assert.match(ui.context.recordingStatusText({configured: true, active: true, healthy: false}), /waiting/i);
  assert.match(ui.context.recordingStatusText({configured: true, stopping: true}), /finalizing/i);
});

test("recording test refresh failures cannot replace the original encoder failure", async () => {
  const ui = app(functionsBetween("async function testRecordingSettings(", "function sessionTime("), async () => { throw new Error("encoder failed"); });
  ui.context.loadRecordingSettings = async () => { throw new Error("refresh failed"); };
  const button = ui.mount("recordingTest");
  await assert.rejects(ui.context.testRecordingSettings(), /encoder failed/);
  assert.equal(button.disabled, false);
});

test("mark highlight submits once while a save is pending and re-enables on failure", async () => {
  let reject, calls = 0;
  const ui = app(functionsBetween("let productionReplayMarkPending=", "async function takeProductionReplay("), async () => { calls++; return new Promise((_, no) => { reject = no; }); });
  ui.context.loadProductionReplay = async () => ({});
  const button = ui.mount("productionReplayMark");
  const first = ui.context.markProductionReplay();
  await ui.context.markProductionReplay();
  assert.equal(calls, 1);
  assert.equal(button.disabled, true);
  reject(new Error("storage unavailable"));
  await assert.rejects(first, /storage unavailable/);
  assert.equal(button.disabled, false);
  assert.equal(ui.notices.length, 0);
});

test("a saved highlight remains a success if only the history refresh fails", async () => {
  const ui = app(functionsBetween("let productionReplayMarkPending=", "async function takeProductionReplay("), async () => ({ok: true, created: true, highlight: {name: "Big pull"}}));
  ui.context.loadProductionReplay = async () => { throw new Error("refresh unavailable"); };
  await ui.context.markProductionReplay();
  assert.equal(ui.notices[0][0], "Highlight Saved");
});
