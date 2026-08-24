
const $=(id)=>document.getElementById(id);
function switchWorkspace(name){
  document.querySelectorAll(".workspace").forEach(el=>el.classList.toggle("active",el.dataset.workspace===name));
  document.querySelectorAll(".nav-btn").forEach(el=>el.classList.toggle("active",el.dataset.target===name));
  const titles={
    live:["Live","Active ripping and recognition"],
    collection:["Collection","Scans, sessions, and exports"],
    creator:["Creator","Branding, overlays, reactions, and output"],
    library:["Library","Metadata, artwork, indexing, and maintenance"],
    settings:["Settings","Camera, APIs, logs, and developer tools"]
  };
  const value=titles[name]||titles.live;
  $("pageTitle").textContent=value[0];
  $("pageSubtitle").textContent=value[1];
}
async function api(path,options={}){
  const response=await fetch(path,{cache:"no-store",headers:{"Content-Type":"application/json"},...options});
  return response.json();
}
async function loadCamera(){
  try{
    const status=await api("/api/camera/status");
    $("cameraState").textContent=status.running||status.connected?"CAMERA ONLINE":"CAMERA OFFLINE";
  }catch{$("cameraState").textContent="CAMERA UNKNOWN"}
  $("cameraFeed").src="/api/camera/frame?ts="+Date.now();
}
async function loadRecognition(){
  try{
    const result=await api("/api/recognition-state");
    const state=result.state||result||{};
    const payload=state.payload||state.latest||{};
    const card=payload.card||payload.match||payload.current_card||null;
    const confidence=Number(payload.confidence||payload.fused_score||0);
    $("aiState").textContent=card?"VERIFIED":(payload.status?String(payload.status).toUpperCase():"WATCHING");
    $("aiDetail").textContent=card?"Card matched against the local index.":"Place a card inside the scan frame.";
    if(card){
      $("cardName").textContent=card.name||card.printed_name||"Recognized Card";
      $("cardMeta").textContent=[card.set_name,card.collector_number,card.language,card.rarity].filter(Boolean).join(" • ");
      $("cardValue").textContent=card.market_price?`$${Number(card.market_price).toFixed(2)}`:"VALUE PENDING";
      const image=card.reference_image_url||card.local_image||"";
      if(image)$("cardArt").innerHTML=`<img src="${image}" alt="">`;
    }
    setSignal("vision",Number(payload.visual_score||payload.artwork_score||confidence));
    setSignal("ocr",Number(payload.ocr_score||0));
    setSignal("collector",Number(payload.collector_score||0));
    setSignal("fusion",confidence);
  }catch{}
}
function setSignal(name,value){
  const normalized=value>1?value/100:value;
  const percent=Math.max(0,Math.min(100,Math.round(normalized*100)));
  $(`${name}Bar`).style.width=`${percent}%`;
  $(`${name}Value`).textContent=`${percent}%`;
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
  const next=Number($("packNo").textContent||1)+1;
  await updateOverlay({pack_number:next,pack_total:0});
}
function openProgram(){window.open("/program","rareiq-program","width=1280,height=720")}
async function loadBrand(){
  const result=await api("/api/brand");
  const brand=result.brand||{};
  Object.entries(brand).forEach(([k,v])=>{
    const field=document.querySelector(`[data-brand="${k}"]`);
    if(field)field.value=v;
  });
  applyBrand(brand);
}
function currentBrand(){
  const settings={};
  document.querySelectorAll("[data-brand]").forEach(field=>settings[field.dataset.brand]=field.value);
  return settings;
}
function applyBrand(brand){
  const map={background:"--bg",panel:"--panel",border:"--border",primary:"--primary",secondary:"--success",intelligence:"--intel",gold:"--gold",danger:"--danger",text:"--text",muted:"--muted"};
  Object.entries(map).forEach(([k,v])=>{if(brand[k])document.documentElement.style.setProperty(v,brand[k])});
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
  }catch{$("maintenanceStatus").textContent=`${label} failed.`}
}
document.addEventListener("DOMContentLoaded",()=>{
  document.querySelectorAll(".nav-btn").forEach(button=>button.addEventListener("click",()=>switchWorkspace(button.dataset.target)));
  document.querySelectorAll("[data-brand]").forEach(field=>field.addEventListener("input",()=>applyBrand(currentBrand())));
  loadBrand();loadCamera();loadRecognition();loadOverlay();
  setInterval(loadCamera,1800);
  setInterval(loadRecognition,650);
  setInterval(loadOverlay,1500);
});
