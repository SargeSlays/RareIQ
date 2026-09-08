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
  const context = vm.createContext({$: id => nodes.get(id) || null, api, notify: (...args) => notices.push(args), crypto:require("node:crypto").webcrypto, console});
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
  const ui = app(functionsBetween("let productionReplayMarkPending=", "async function takeProductionReplay("), async () => ({ok: true, created: true, highlight: {name: "Big pull",video_available:true,duration_seconds:8}}));
  ui.context.loadProductionReplay = async () => { throw new Error("refresh unavailable"); };
  await ui.context.markProductionReplay();
  assert.equal(ui.notices[0][0], "Highlight Saved");
});

test("manual clip request captures expiry and reports actual silent camera coverage",async()=>{
  let request;
  const ui=app(functionsBetween("let productionReplayMarkPending=","async function takeProductionReplay("),async(path,options)=>{request=JSON.parse(options.body);assert.equal(options.retries,0);return {ok:true,actual_seconds:19.4,shorter_than_requested:true,highlight:{video_available:true,audio_tracks:0,source_kind:'program_camera'}};});
  ui.context.loadProductionReplay=async()=>({});ui.mount('productionReplayLength',{value:'120'});
  await ui.context.markProductionReplay();assert.match(request.request_id,/^[a-f\d-]{36}$/);assert.equal(request.expires_at-request.ending_at,90);assert.equal(request.seconds,120);
  assert.match(ui.notices[0][1],/silent Program-camera clip/);assert.match(ui.notices[0][1],/19.4s of the requested 120s/);
});

test("pending clip request reuses identity and never announces a save",async()=>{
  const requests=[];
  const ui=app(functionsBetween("let productionReplayMarkPending=","async function takeProductionReplay("),async(path,options)=>{requests.push(JSON.parse(options.body));return {ok:false,reason:'action_still_running'};});
  ui.context.loadProductionReplay=async()=>({});const button=ui.mount('productionReplayMark');
  await ui.context.markProductionReplay();await ui.context.markProductionReplay();assert.equal(requests[0].request_id,requests[1].request_id);assert.equal(button.textContent,'CHECK SAVE');assert.equal(ui.notices.some(n=>n[0]==='Highlight Saved'),false);
});

test("metadata without confirmed playable video is never called saved",async()=>{
  const ui=app(functionsBetween("let productionReplayMarkPending=","async function takeProductionReplay("),async()=>({ok:true,highlight:{name:'Metadata only'}}));
  await assert.rejects(ui.context.markProductionReplay(),/No playable clip/);assert.equal(ui.notices.length,0);
});
