const {test}=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs"), path=require("node:path"), vm=require("node:vm");
const root=path.resolve(__dirname,"../../rareiq/web/static");
const source=fs.readFileSync(path.join(root,"studiox.js"),"utf8");
const shared=fs.readFileSync(path.join(root,"multi_card_state.js"),"utf8");
const verified=(slot=1)=>({slot,status:"verified",verified:true,confidence:.93,card:{canonical_name:`Card ${slot}`,reference_image_url:"/static/reference.png"}});
const review=(slot=1)=>({slot,status:"review-needed",card:{canonical_name:"Armarouge"}});
function rules(){const context=vm.createContext({window:{}});vm.runInContext(shared,context);return context.window.RareIQMultiCard;}

test("completed workers do not imply ready cards; unknown confidence is not 0%",()=>{
  const state=rules(), payload={status:"complete",completed_count:1,detected_count:1,slots:[review()]};
  assert.match(state.presentation(payload).summary,/0 of 1 verified.*1 need review/);
  assert.equal(state.presentation(payload).state,"warning");
  assert.equal(state.name(payload.slots[0].card),"Armarouge");
  assert.equal(state.confidence(payload.slots[0]),"Not scored");
  assert.equal(state.confidence({confidence:0,card:{confidence:.8}}),"0%");
});
test("all verified and mixed results have distinct success and review states",()=>{
  const state=rules();
  assert.equal(state.presentation({status:"complete",slots:[verified()]}).state,"complete");
  assert.match(state.presentation({status:"complete",slots:[verified(),review(2)]}).summary,/1 of 2 verified/);
  assert.match(state.presentation({status:"recognizing",slots:[review(),{slot:2,status:"recognizing"}]}).summary,/1 of 2 analyzed · 0 verified/);
});
test("saved, empty, and failed scans never advertise fresh ready results",()=>{
  const state=rules();
  assert.equal(state.presentation({status:"complete",restored:true,slots:[review()]}).badge,"Saved scan");
  assert.match(state.presentation({status:"complete",slots:[]}).summary,/No complete/);
  assert.equal(state.presentation({status:"no-cards-detected",ok:false,slots:[]}).badge,"No cards found");
  assert.equal(state.presentation({status:"complete",ok:false,slots:[verified()]}).state,"warning");
});
test("only detected slots appear and stored capacity does not hide actual results",()=>{
  const slots=rules().visibleSlots({max_cards:2,slots:[verified(1),{slot:2,status:"not-detected"},review(12),{slot:13,status:"verified"}]});
  assert.equal(slots.length,2);assert.equal(slots[1].slot,12);
});
test("output gate cannot be bypassed by a candidate, interim state, or stale flag",()=>{
  const state=rules();assert.equal(state.ready(verified()),true);
  for(const item of [review(),{...verified(),output_ready:false},{...verified(),status:"recognizing"},{...verified(),exact_version_unresolved:true},{...verified(),card:{name:"A",provisional:true}},{...verified(),card:{}}])assert.equal(state.ready(item),false);
});
test("reference URLs preserve actual URLs and encode local catalog paths",()=>{
  const state=rules();
  assert.equal(state.referenceImage({reference_image:"https://example.test/card.png"}),"https://example.test/card.png");
  assert.equal(state.referenceImage({reference_image:"C:\\cards\\sample.png"}),"/api/reference-image?path=C%3A%5Ccards%5Csample.png");
  assert.equal(state.referenceImage({}),"");
});

function element(tag="div"){
  const classes=new Set();
  return {tag,textContent:"",dataset:{},children:[],hidden:false,disabled:false,attributes:{},
    classList:{toggle:(n,on)=>on?classes.add(n):classes.delete(n),add:n=>classes.add(n),remove:n=>classes.delete(n),contains:n=>classes.has(n)},
    style:{setProperty(){}},
    append(...items){for(const item of items){item.parent=this;this.children.push(item);}},appendChild(item){this.append(item);},
    replaceChildren(...items){this.children=[];this.append(...items);},remove(){if(this.parent)this.parent.children=this.parent.children.filter(x=>x!==this);},
    after(item){this.parent?.append(item);},setAttribute(n,v){this.attributes[n]=v;},getAttribute(n){return n==="src"?this.src:this.attributes[n];},
    querySelector(selector){return this.children.find(x=>selector.startsWith(".")?x.className===selector.slice(1):x.tag===selector)||null;}
  };
}
function ui(api=async()=>({slots:[]})){
  const nodes=new Map(),slots=Array.from({length:12},(_,i)=>{const n=element("article");n.dataset.multiCardSlot=String(i+1);return n;});
  for(const id of ["multiCardResults","multiCardReadiness","multiCardStateBadge","multiCardSummary","multiCardGuidance","multiCardSelectionStatus","multiCardEmpty"])nodes.set(id,element());
  const context=vm.createContext({window:{},api,console:{warn(){}},studioXRecognitionMode:"six-card-grid",multiCardPollTimer:null,setTimeout:()=>1,clearTimeout(){},recognitionMutationInFlight:()=>false,setRecognitionCaptureBusy(){},notify(){},$:id=>nodes.get(id)||null,setCardText:(id,text)=>{if(nodes.has(id))nodes.get(id).textContent=text;},document:{createElement:element,querySelectorAll:()=>slots,querySelector:s=>slots[Number(s.match(/"(\d+)"/)?.[1])-1]||null}});
  vm.runInContext(shared,context);
  context.renderCameraRecognitionPresentation=()=>{};
  vm.runInContext(source.slice(source.indexOf("function multiCardName("),source.indexOf("const VIRTUAL_CAMERA_TERMS=")),context);
  return {context,nodes,slots};
}
function cameraUI(){
  const nodes=new Map(["cameraFeedStateLabel","aiState","aiDetail","unifiedScanStatus","recognitionStateLabel","recognitionStateDetail","recognitionStatePanel"].map(id=>[id,element()]));
  const workspace=element();
  const context=vm.createContext({window:{},latestSingleCameraPresentation:null,
    studioXRecognitionMode:"six-card-grid",multiCardLastPayload:null,
    cameraConnectionAvailable:true,cameraConnectionFailure:null,cardPlaceholderResetTimer:null,
    $:id=>nodes.get(id)||null,normalize:x=>x,updateConfidenceRing(){},clearTimeout(){},
    setStateChip(){},updateAiPulse(){},setCoreState(){},
    document:{body:element(),querySelectorAll:()=>[],querySelector:()=>workspace}});
  vm.runInContext(shared,context);
  vm.runInContext(source.slice(source.indexOf("function applyRecognitionPresentation("),source.indexOf("function renderRecognitionLatencyTrace(")),context);
  return {context,nodes,workspace};
}

test("both camera badges follow grid results despite ongoing single-card events",()=>{
  const app=cameraUI();
  const cases=[
    [{status:"idle"},"READY TO SCAN"],
    [{status:"detecting",max_cards:3},"FINDING CARDS"],
    [{status:"recognizing",slots:[verified(),{slot:2,status:"recognizing"}]},"RECOGNITION ACTIVE"],
    [{status:"complete",slots:[verified(),verified(2),verified(3)]},"SCAN COMPLETE"],
    [{status:"complete",slots:[verified(),review(2)]},"REVIEW NEEDED"],
    [{status:"complete",restored:true,slots:[verified()]},"SAVED SCAN"],
    [{status:"no-cards-detected",ok:false},"NO CARDS FOUND"],
    [{status:"error",ok:false},"SCAN UNAVAILABLE"],
  ];
  for(const [payload,title] of cases){
    app.context.multiCardLastPayload=payload;
    app.context.renderCameraRecognitionPresentation();
    for(const key of ["candidate-found","verifying","ready"]){
      app.context.applyRecognitionPresentation({key,title:"STALE SINGLE CARD",detail:"single-card evidence"});
      for(const id of ["cameraFeedStateLabel","aiState","recognitionStateLabel"])assert.equal(app.nodes.get(id).textContent,title);
      assert.equal(app.nodes.get("aiDetail").textContent,app.nodes.get("recognitionStateDetail").textContent);
      assert.equal(app.nodes.get("recognitionStateDetail").textContent,app.context.window.RareIQMultiCard.cameraPresentation(payload).detail);
    }
  }
});

test("camera disconnect wins; recovery and mode changes restore the active workflow",()=>{
  const app=cameraUI();app.context.multiCardLastPayload={status:"complete",slots:[verified()]};
  app.context.cameraConnectionAvailable=false;
  app.context.applyRecognitionPresentation({key:"candidate-found",title:"CANDIDATE FOUND",detail:"Latest single result"});
  assert.equal(app.nodes.get("cameraFeedStateLabel").textContent,"CAMERA OFFLINE");
  app.context.cameraConnectionAvailable=true;app.context.renderCameraRecognitionPresentation();
  assert.equal(app.nodes.get("cameraFeedStateLabel").textContent,"SCAN COMPLETE");
  Object.assign(app.context,{localStorage:{setItem(){}},STUDIOX_RECOGNITION_MODE_KEY:"mode",syncRecognitionModeWorkspace(){},requestAnimationFrame(){},loadMultiCardStatus(){},multiCardPollTimer:null,renderMultiCardCameraOverlay(){}});
  vm.runInContext(source.slice(source.indexOf("function setRecognitionMode("),source.indexOf("function multiCardName(")),app.context);
  app.context.setRecognitionMode("single");
  assert.equal(app.nodes.get("cameraFeedStateLabel").textContent,"CANDIDATE FOUND");
  app.context.setRecognitionMode("six-card-grid");
  assert.equal(app.nodes.get("recognitionStateLabel").textContent,"SCAN COMPLETE");
});

test("rendering a smaller scan clears previous tiles and blocks Show for a review candidate",()=>{
  const app=ui();app.context.renderMultiCardStatus({status:"complete",slots:[verified(),verified(2),review(3)]});
  app.context.renderMultiCardStatus({status:"complete",slots:[review()]});
  assert.equal(app.slots.filter(n=>!n.hidden).length,1);
  assert.equal(app.slots[1].children.length,0);
  assert.equal(app.slots[0].querySelector("strong").textContent,"Armarouge");
  assert.equal(app.slots[0].querySelector(".multi-card-show-toggle").disabled,true);
});

test("restored or failed scans keep result cards but never draw old coordinates over a live camera",()=>{
  const app=ui();let drawn;
  app.context.renderMultiCardCameraOverlay=slots=>{drawn=slots;};
  for(const flags of [{restored:true},{ok:false}]){
    app.context.renderMultiCardStatus({status:"complete",slots:[verified()],...flags});
    assert.equal(drawn.length,0);
    assert.equal(app.slots[0].hidden,false);
  }
  app.context.renderMultiCardStatus({status:"complete",slots:[verified()],restored:false});
  assert.equal(drawn.length,1);
});
test("stable polls preserve tile controls; image failure has an explicit fallback",()=>{
  const app=ui(),payload={status:"complete",slots:[verified()]};app.context.renderMultiCardStatus(payload);
  const button=app.slots[0].querySelector(".multi-card-show-toggle"),image=app.slots[0].querySelector("img");
  image.onerror();app.context.renderMultiCardStatus(payload);
  assert.equal(app.slots[0].querySelector(".multi-card-show-toggle"),button);
  assert.equal(image.hidden,true);
  assert.match(app.slots[0].querySelector(".multi-card-artwork-note").textContent,/unavailable/);
});
test("selection submits only verified cards and double clicks share one mutation",async()=>{
  let resolve,calls=[];
  const app=ui(async(url,options)=>{calls.push(url);if(options)return new Promise(yes=>{resolve=yes;});return {slots:[verified()],selected_slots:[]};});
  app.context.renderMultiCardStatus({status:"complete",slots:[verified()]});
  const first=app.context.toggleMultiCardOutput(1);await Promise.resolve();
  await app.context.toggleMultiCardOutput(1);
  assert.equal(await app.context.captureMultiCardGrid(),null);
  assert.equal(calls.some(url=>url.endsWith("/capture")),false);
  resolve({status:"complete",slots:[verified()],selected_slots:[1]});await first;
  assert.equal(calls.filter(url=>url.endsWith("/select")).length,1);
  assert.equal(app.slots[0].querySelector(".multi-card-show-toggle").textContent,"Hide from screen");
});
test("fresh server review state blocks selection even if the UI previously showed verified",async()=>{
  const calls=[];const app=ui(async url=>{calls.push(url);return {slots:[review()]};});
  app.context.renderMultiCardStatus({status:"complete",slots:[verified()]});
  await assert.rejects(app.context.toggleMultiCardOutput(1),/needs verification/);
  assert.equal(calls.length,1);
  assert.equal(app.slots[0].querySelector(".multi-card-show-toggle").disabled,true);
});
test("failed status requests disable output and later polling can recover",async()=>{
  const app=ui(async()=>{throw new Error("offline");});
  app.context.renderMultiCardStatus({status:"complete",slots:[verified()]});
  await Promise.all([app.context.loadMultiCardStatus(),app.context.loadMultiCardStatus()]);
  assert.equal(app.slots[0].querySelector(".multi-card-show-toggle").disabled,true);
  app.context.api=async()=>({status:"complete",slots:[verified()]});await app.context.loadMultiCardStatus();
  assert.equal(app.slots[0].querySelector(".multi-card-show-toggle").disabled,false);
});

test("browser source filters provisional selections and clears immediately on failure",()=>{
  const stage=element(),grid=element();let transport;
  const context=vm.createContext({window:{RareIQOverlay:{start:options=>{transport=options;}}},document:{getElementById:id=>id==="stage"?stage:grid,createElement:element}});
  vm.runInContext(shared,context);vm.runInContext(fs.readFileSync(path.join(root,"overlay_multicard.js"),"utf8"),context);
  transport.render({slots:[verified(),review(2)],selected_slots:[1,2]});
  assert.equal(grid.children.length,1);assert.equal(stage.classList.contains("live"),true);
  transport.render({slots:[review()],selected_slots:[1]});assert.equal(grid.children.length,0);
  transport.render({slots:[verified()],selected_slots:[1]});transport.clear();
  assert.equal(stage.classList.contains("live"),false);assert.equal(grid.children.length,0);
});
