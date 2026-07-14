
const $=(id)=>document.getElementById(id);
let previousCardId=null;

function switchWorkspace(name){
  document.querySelectorAll(".workspace").forEach(el=>el.classList.toggle("active",el.dataset.workspace===name));
  document.querySelectorAll(".nav-btn").forEach(el=>el.classList.toggle("active",el.dataset.target===name));
  const titles={
    live:["Live","Active ripping and recognition"],
    collection:["Collection","Scans, sessions, and exports"],
    creator:["Creator","Branding, overlays, reactions, and output"],
    library:["Library","Metadata, artwork, indexing, and maintenance"],
    settings:["Settings","Camera, output, APIs, and developer tools"]
  };
  const [title,subtitle]=titles[name]||titles.live;
  $("pageTitle").textContent=title;
  $("pageSubtitle").textContent=subtitle;
}

async function api(path,options={}){
  const response=await fetch(path,{cache:"no-store",headers:{"Content-Type":"application/json"},...options});
  return response.json();
}

async function loadCamera(){
  try{
    const status=await api("/api/camera/status");
    const online=Boolean(status.running||status.connected);
    $("cameraState").textContent=online?"CAMERA ONLINE":"CAMERA OFFLINE";
    $("cameraState").style.color=online?"var(--green)":"var(--red)";
  }catch{
    $("cameraState").textContent="CAMERA UNKNOWN";
  }
  $("cameraFeed").src="/api/camera/frame?ts="+Date.now();
}

async function loadRecognition(){
  try{
    const result=await api("/api/recognition-state");
    const state=result.state||result||{};
    const payload=state.payload||state.latest||{};
    const card=payload.card||payload.match||payload.current_card||null;
    const confidence=normalize(payload.confidence||payload.fused_score||0);
    const status=String(payload.status||"").toLowerCase();

    const zone=$("scanZone");
    zone.classList.toggle("detected",status.includes("detect")||Boolean(card));
    zone.classList.toggle("verified",Boolean(card)&&confidence>=.68);

    $("aiState").textContent=card?"VERIFIED":status?status.toUpperCase():"WATCHING";
    $("aiDetail").textContent=card?"Card matched against the local index.":"Place a card inside the scan zone.";
    $("confidenceBadge").textContent=`${Math.round(confidence*100)}%`;

    if(card){
      const cardId=card.id||`${card.set_id||""}:${card.collector_number||""}:${card.name||""}`;
      $("cardName").textContent=card.name||card.printed_name||"Recognized Card";
      $("cardMeta").textContent=[card.set_name,card.collector_number,card.language,card.rarity].filter(Boolean).join(" • ");
      const value=Number(card.market_price||card.price||0);
      $("cardValue").textContent=value>0?`$${value.toFixed(2)}`:"VALUE PENDING";
      $("verifiedText").textContent=confidence>=.9?"HIGH CONFIDENCE MATCH":confidence>=.68?"CANDIDATE MATCH":"REVIEW REQUIRED";

      const image=card.reference_image_url||card.local_image||"";
      if(image)$("cardArt").innerHTML=`<img src="${image}" alt="">`;

      if(cardId&&previousCardId&&cardId!==previousCardId&&value>=100){
        triggerHit();
      }
      previousCardId=cardId;
    }

    setSignal("vision",payload.visual_score||payload.artwork_score||confidence);
    setSignal("ocr",payload.ocr_score||0);
    setSignal("collector",payload.collector_score||0);
    setSignal("fusion",confidence);

    renderPipeline(payload.pipeline_stages||[],Boolean(card));
  }catch{}
}

function normalize(value){
  const number=Number(value||0);
  return Math.max(0,Math.min(1,number>1?number/100:number));
}

function setSignal(name,value){
  const percent=Math.round(normalize(value)*100);
  $(`${name}Bar`).style.width=`${percent}%`;
  $(`${name}Value`).textContent=`${percent}%`;
}

function renderPipeline(stages,hasCard){
  const done=new Set(
    stages.filter(stage=>stage.status==="done"||stage.done)
      .map(stage=>String(stage.key||stage.name||"").toLowerCase())
  );
  const order=["detect","prepare","read","match","verify"];
  document.querySelectorAll(".process").forEach((el,index)=>{
    const key=el.dataset.key;
    const isDone=done.has(key)||done.has(el.dataset.alt||"")||(hasCard&&index<4);
    el.classList.toggle("done",isDone);
    el.classList.toggle("active",!isDone&&index===Math.min(done.size,4));
  });
}

function triggerHit(){
  document.body.classList.remove("hit-mode");
  void document.body.offsetWidth;
  document.body.classList.add("hit-mode");
  $("scanZone").classList.add("hit");
  setTimeout(()=>$("scanZone").classList.remove("hit"),1000);
}

async function loadOverlay(){
  const result=await api("/api/overlay/state");
  const state=result.state||{};
  $("packNo").textContent=state.pack_number||1;
  $("packValue").textContent=`$${Number(state.pack_total||0).toFixed(2)}`;
  $("boxValue").textContent=`$${Number(state.box_total||0).toFixed(2)}`;
  $("sessionValue").textContent=`$${Number(state.session_total||0).toFixed(2)}`;
}

async function updateOverlay(state){
  await api("/api/overlay/state",{method:"POST",body:JSON.stringify({state})});
  await loadOverlay();
}

async function nextPack(){
  await updateOverlay({pack_number:Number($("packNo").textContent||1)+1,pack_total:0});
}

function openProgram(){window.open("/program","rareiq-program","width=1280,height=720")}

async function loadBrand(){
  const result=await api("/api/brand");
  const brand=result.brand||{};
  Object.entries(brand).forEach(([key,value])=>{
    const field=document.querySelector(`[data-brand="${key}"]`);
    if(field)field.value=value;
  });
  applyBrand(brand);
}

function currentBrand(){
  const settings={};
  document.querySelectorAll("[data-brand]").forEach(field=>settings[field.dataset.brand]=field.value);
  return settings;
}

function applyBrand(brand){
  const map={background:"--bg",panel:"--surface",border:"--line",primary:"--cyan",secondary:"--green",intelligence:"--purple",gold:"--gold",danger:"--red",text:"--text",muted:"--muted"};
  Object.entries(map).forEach(([key,variable])=>{
    if(brand[key])document.documentElement.style.setProperty(variable,brand[key]);
  });
}

async function saveBrand(){
  const settings=currentBrand();
  const result=await api("/api/brand",{method:"POST",body:JSON.stringify({settings})});
  applyBrand(result.brand||settings);
  document.querySelectorAll(".preview iframe").forEach(frame=>frame.src=frame.src.split("?")[0]+"?ts="+Date.now());
}

async function maintenance(path,label){
  $("maintenanceStatus").textContent=`${label} started…`;
  try{
    const result=await api(path,{method:"POST",body:"{}"});
    $("maintenanceStatus").textContent=result.ok===false?(result.error||`${label} failed.`):`${label} queued.`;
  }catch{
    $("maintenanceStatus").textContent=`${label} failed.`;
  }
}

document.addEventListener("DOMContentLoaded",()=>{
  document.querySelectorAll(".nav-btn").forEach(button=>button.addEventListener("click",()=>switchWorkspace(button.dataset.target)));
  document.querySelectorAll("[data-brand]").forEach(field=>field.addEventListener("input",()=>applyBrand(currentBrand())));
  loadBrand();
  loadCamera();
  loadRecognition();
  loadOverlay();
  setInterval(loadCamera,1800);
  setInterval(loadRecognition,600);
  setInterval(loadOverlay,1500);
});
