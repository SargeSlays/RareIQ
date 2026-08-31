const {test}=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const root=path.resolve(__dirname,"../../rareiq/web/static");
const source=fs.readFileSync(path.join(root,"studiox.js"),"utf8");
const html=fs.readFileSync(path.join(root,"control.html"),"utf8");
const nodes=new Map(["recognitionSpeed","recognitionSpeedLabel","recognitionSpeedValue"].map(id=>[id,{dataset:{},textContent:"",title:""}]));
const runtime=vm.createContext({$:id=>nodes.get(id)||null});
vm.runInContext(source.slice(source.indexOf("function deriveRecognitionSpeed("),source.indexOf("function renderRecognitionLatencyTrace(")),runtime);
const derive=runtime.deriveRecognitionSpeed;
const result=(key="exact-match",timings={capture_to_result_ms:756,total_ms:720})=>({presentation:{key},verified:key==="exact-match",card:{id:"me5-1"},snapshot:{generation:3,result_current:true,stage_timings:timings}});

test("match speed is visible in the workspace header, outside hidden diagnostics",()=>{
  const header=html.slice(html.indexOf('<header class="studiox-recognition-workspace-head">'),html.indexOf('<section class="studiox-live-analysis"'));
  assert.match(header,/id="recognitionSpeed"/);
  assert.match(header,/id="recognitionSpeedValue"/);
  assert.doesNotMatch(header,/\shidden(?:[\s=>])|recognitionLatencyTrace/);
  const update=source.slice(source.indexOf("function updateSharedCardContext("),source.indexOf("function applyStudioXExactMatchMoment("));
  assert.match(update,/renderRecognitionSpeed\(context\)/);
  const apply=source.slice(source.indexOf("function applyRecognitionPresentation("),source.indexOf("function renderCameraRecognitionPresentation("));
  assert.match(apply,/\["ready","detecting","scanning","error"\].includes\(key\)/);
  assert.match(apply,/renderRecognitionSpeed\(\{presentation\}\)/);
});

test("verified speed uses capture-to-result elapsed time, not overlapping stage sums",()=>{
  const context=result("exact-match",{capture_to_result_ms:756,total_ms:720,artwork_preflight_ms:500,artwork_search_ms:500});
  const model=derive(context);
  assert.equal(model.label,"Matched in");
  assert.equal(model.value,"756 ms");
  assert.match(model.title,/including queueing/);
});

test("candidates and review results never claim a verified match",()=>{
  for(const key of ["candidate-found","verifying"]){
    assert.equal(derive(result(key)).label,"Candidate in");
    assert.match(derive(result(key)).title,/not yet verified/);
  }
  for(const key of ["review-needed","set-mismatch"]){
    assert.equal(derive(result(key)).label,"Analyzed in");
  }
  assert.notEqual(derive({...result(),verified:false}).label,"Matched in");
});

test("missing and invalid timings never become invented zero-millisecond matches",()=>{
  for(const value of [undefined,null,""," ",false,true,[],{},-1,Infinity,NaN,"no"]){
    const model=derive(result("exact-match",{capture_to_result_ms:value,total_ms:value}));
    assert.equal(model.value,"—");
    assert.equal(model.state,"idle");
  }
});

test("processing fallback is labeled accurately and formats ms and seconds",()=>{
  for(const [total_ms,expected] of [[0,"<1 ms"],[.1,"<1 ms"],[612,"612 ms"],[1324,"1.32 s"],[9240,"9.24 s"],["820","820 ms"]]){
    const model=derive(result("candidate-found",{total_ms}));
    assert.equal(model.value,expected);
    assert.match(model.title,/Recognition processing time/);
  }
  const context=result();context.snapshot.stage_timings={};
  context.snapshot.raw_recognition={generation:3,last_latency_ms:432};
  assert.equal(derive(context).value,"432 ms");
});

test("idle, disconnect, handoff, or stale generations clear the previous speed",()=>{
  for(const key of ["ready","detecting","scanning","error"]){
    assert.equal(derive(result(key)).value,"—");
  }
  const context=result();context.snapshot.result_current=false;
  assert.equal(derive(context).value,"—");
  context.snapshot.result_current=true;
  context.snapshot.raw_recognition={generation:2,last_latency_ms:123};
  assert.equal(derive(context).value,"—");
});

test("renderer updates and clears the same badge instead of retaining stale text",()=>{
  runtime.renderRecognitionSpeed(result());
  assert.equal(nodes.get("recognitionSpeedValue").textContent,"756 ms");
  assert.equal(nodes.get("recognitionSpeed").dataset.state,"matched");
  runtime.renderRecognitionSpeed(result("error"));
  assert.equal(nodes.get("recognitionSpeedValue").textContent,"—");
  assert.equal(nodes.get("recognitionSpeedLabel").textContent,"Match speed");
  runtime.renderRecognitionSpeed(result("candidate-found",{total_ms:1432}));
  assert.equal(nodes.get("recognitionSpeedValue").textContent,"1.43 s");
  assert.equal(nodes.get("recognitionSpeedLabel").textContent,"Candidate in");
  assert.equal(nodes.get("recognitionSpeed").dataset.state,"candidate");
});
