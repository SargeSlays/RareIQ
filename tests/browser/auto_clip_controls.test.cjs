const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.resolve(__dirname, "../../rareiq/web/static/studiox.js"), "utf8");
const code = source.slice(source.indexOf("let productionReplayRefreshTimer="), source.indexOf("let productionReplayMarkPending="));
const initial = () => ({enabled:false, saving:false, pending_count:0, saved_count:0, config:{minimum_tier:"medium",pre_seconds:5,post_seconds:3}});
function app(api = async () => initial()) {
  const nodes = new Map();
  for (const id of ["productionAutoClipArm","productionAutoClipTier","productionAutoClipPre","productionAutoClipPost","productionAutoClipSave","productionAutoClipStatus"]) nodes.set(id,{disabled:false,value:"",textContent:"",setAttribute(name,value){this[name]=value;}});
  const context = vm.createContext({api, $:id=>nodes.get(id), setInterval:()=>1, document:{hidden:false,body:{dataset:{ui4Workspace:"broadcast"}}}, renderProductionReplay:()=>{}});
  vm.runInContext(code,context);
  context.renderProductionAutoClip(initial());
  return {context,nodes};
}
test("settings polls preserve edits and require saving before arming", () => {
  const ui=app();
  ui.nodes.get("productionAutoClipPre").value="9";
  ui.context.renderProductionAutoClip(initial());
  assert.equal(ui.nodes.get("productionAutoClipPre").value,"9");
  assert.equal(ui.nodes.get("productionAutoClipArm").disabled,true);
  assert.match(ui.nodes.get("productionAutoClipStatus").textContent,/Unsaved/);
});
test("armed mode locks settings but leaves disarm available during encoding", () => {
  const ui=app();
  ui.context.renderProductionAutoClip({...initial(),enabled:true,saving:true});
  assert.equal(ui.nodes.get("productionAutoClipPre").disabled,true);
  assert.equal(ui.nodes.get("productionAutoClipArm").disabled,false);
  assert.equal(ui.nodes.get("productionAutoClipArm")["aria-pressed"],"true");
  assert.equal(ui.nodes.get("productionAutoClipArm").textContent,"Disarm Auto Clip");
});
test("arming double clicks submit once and success never initiates playback", async () => {
  let resolve;
  const calls=[];
  const ui=app((path,options)=>{calls.push([path,JSON.parse(options.body)]);return new Promise(yes=>{resolve=yes;});});
  const first=ui.context.updateProductionAutoClip("arm");
  await ui.context.updateProductionAutoClip("arm");
  assert.equal(calls.length,1);
  assert.deepEqual(calls[0],["/api/production/auto-clip/arm",{enabled:true}]);
  resolve({...initial(),enabled:true});await first;
  assert.equal(ui.nodes.get("productionAutoClipArm").disabled,false);
  assert.equal(ui.nodes.get("productionAutoClipArm").textContent,"Disarm Auto Clip");
});
test("failed or uncertain mutation does not claim success or keep stale controls enabled", async () => {
  const ui=app(async()=>{throw new Error("storage unavailable");});
  await assert.rejects(ui.context.updateProductionAutoClip("settings"),/storage unavailable/);
  assert.equal(ui.nodes.get("productionAutoClipArm").disabled,true);
  assert.match(ui.nodes.get("productionAutoClipStatus").textContent,/unavailable/);
  ui.context.renderProductionAutoClip(initial());
  assert.equal(ui.nodes.get("productionAutoClipArm").disabled,false);
});
test("settings save sends current fields without implicitly arming", async () => {
  const calls=[];
  const ui=app(async(path,options)=>{const config=JSON.parse(options.body);calls.push({path,config});return {...initial(),config};});
  ui.nodes.get("productionAutoClipPre").value="8";
  await ui.context.updateProductionAutoClip("settings");
  assert.equal(calls[0].config.pre_seconds,8);
  assert.equal(calls[0].config.enabled,undefined);
  assert.equal(ui.nodes.get("productionAutoClipArm").textContent,"Arm Auto Clip");
});
test("status explains buffer interruption, cancellation, queue, and storage failures", () => {
  const ui=app();
  for(const reason of ["auto_clip_buffer_interrupted","auto_clip_cancelled","auto_clip_queue_full","clip_encoding_failed","replay_storage_unavailable"]){
    const text=ui.context.autoClipStatusText({...initial(),last_result:{created:false,reason}});
    assert.ok(!text.includes(reason));
    assert.match(text,/Disarmed/);
  }
});
test("concurrent refreshes share one request and errors allow later recovery", async () => {
  let reject,calls=0;
  const ui=app(()=>{calls++;return new Promise((_,no)=>{reject=no;});});
  const first=ui.context.loadProductionReplay(),second=ui.context.loadProductionReplay();
  assert.equal(calls,1);
  reject(new Error("offline"));
  await Promise.all([assert.rejects(first,/offline/),assert.rejects(second,/offline/)]);
  ui.context.api=async()=>({auto_clip:initial()});
  await ui.context.loadProductionReplay();
});
