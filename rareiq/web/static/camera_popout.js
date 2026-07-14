
const $=id=>document.getElementById(id);
let fitMode="adaptive";
let wakeLock=null;

async function api(path,options={}){
  const response=await fetch(path,{
    cache:"no-store",
    headers:{"Content-Type":"application/json"},
    ...options
  });
  return response.json();
}

function normalize(value){
  const number=Number(value||0);
  return Math.max(0,Math.min(1,number>1?number/100:number));
}

function setScore(name,value){
  const percent=Math.round(normalize(value)*100);
  $(`${name}Bar`).style.width=`${percent}%`;
  $(`${name}Value`).textContent=`${percent}%`;
}

function setChip(id,on,label){
  const chip=$(id);
  chip.classList.toggle("on",Boolean(on));
  chip.classList.toggle("working",label==="WORKING");
  const b=chip.querySelector("b");
  if(b) b.textContent=label;
}

function applyFit(mode){
  const valid=["adaptive","fill","frame"];
  fitMode=valid.includes(mode)?mode:"adaptive";
  document.body.classList.remove("fit-adaptive","fit-fill","fit-frame","full-frame");
  document.body.classList.add(`fit-${fitMode}`);

  const names={adaptive:"Adaptive",fill:"Fill Crop",frame:"Full Frame"};
  $("fitButton").textContent=names[fitMode];
  $("fitButton").classList.toggle("active",fitMode==="adaptive");
  localStorage.setItem("rareiq.cameraFitMode",fitMode);
}

function cycleFit(){
  const order=["adaptive","fill","frame"];
  const index=order.indexOf(fitMode);
  applyFit(order[(index+1)%order.length]);
}

async function toggleFullscreen(){
  try{
    if(!document.fullscreenElement){
      await document.documentElement.requestFullscreen();
      $("fullscreenButton").textContent="Exit Fullscreen";
    }else{
      await document.exitFullscreen();
      $("fullscreenButton").textContent="Fullscreen";
    }
  }catch{}
}

async function requestWakeLock(){
  if(!("wakeLock" in navigator)) return;
  try{
    wakeLock=await navigator.wakeLock.request("screen");
    $("wakeButton").classList.add("active");
    $("wakeButton").textContent="Screen Awake";
  }catch{}
}

async function releaseWakeLock(){
  if(wakeLock){
    await wakeLock.release();
    wakeLock=null;
  }
  $("wakeButton").classList.remove("active");
  $("wakeButton").textContent="Keep Awake";
}

async function toggleWake(){
  if(wakeLock) await releaseWakeLock();
  else await requestWakeLock();
}

async function capture(){
  $("stateLabel").textContent="CAPTURING";
  $("stateDetail").textContent="Saving corrected card crop…";
  try{
    const result=await api("/api/camera/capture",{method:"POST",body:"{}"});
    if(result.ok){
      $("stateLabel").textContent="CAPTURED";
      $("stateDetail").textContent=result.path?String(result.path).split(/[\\/]/).pop():"Capture saved";
    }else{
      $("stateLabel").textContent="CAPTURE FAILED";
      $("stateDetail").textContent=result.error||"No corrected crop available";
    }
  }catch{
    $("stateLabel").textContent="CAPTURE FAILED";
    $("stateDetail").textContent="Request error";
  }
}

async function loadStatus(){
  try{
    const status=await api("/api/camera/status");
    const online=Boolean(status.running||status.connected);
    setChip("cameraChip",online,online?"ONLINE":"OFFLINE");
    setChip("autoChip",Boolean(status.auto_capture_enabled),"ON");
    if(online){
      $("cameraFeed").src="/api/camera/stream?ts="+Date.now();
    }
  }catch{}
}

async function loadRecognition(){
  try{
    const result=await api("/api/recognition-state");
    const state=result.state||result||{};
    const payload=state.payload||state.latest||{};
    const card=payload.card||payload.match||payload.current_card||null;
    const confidence=normalize(payload.confidence||payload.fused_score||0);

    $("confidence").textContent=`${Math.round(confidence*100)}%`;
    setScore("vision",payload.visual_score||payload.artwork_score||confidence);
    setScore("ocr",payload.ocr_score||0);
    setScore("collector",payload.collector_score||0);
    setScore("fusion",confidence);

    if(card){
      $("stateLabel").textContent="MATCH FOUND";
      $("stateDetail").textContent=[
        card.name||card.printed_name,
        card.collector_number,
        card.language
      ].filter(Boolean).join(" • ");
      setChip("aiChip",true,"MATCH");
    }else if(payload.status){
      $("stateLabel").textContent=String(payload.status).toUpperCase();
      $("stateDetail").textContent="RareIQ is processing the live card.";
      setChip("aiChip",false,"WORKING");
    }else{
      $("stateLabel").textContent="WATCHING";
      $("stateDetail").textContent="Place a card inside the scan zone.";
      setChip("aiChip",false,"IDLE");
    }
  }catch{}
}

document.addEventListener("DOMContentLoaded",()=>{
  const saved=localStorage.getItem("rareiq.cameraFitMode")||"adaptive";
  applyFit(saved);

  const feed=$("cameraFeed");
  feed.addEventListener("load",()=>$("placeholder").classList.add("hidden"));
  feed.addEventListener("error",()=>$("placeholder").classList.remove("hidden"));

  document.addEventListener("fullscreenchange",()=>{
    $("fullscreenButton").textContent=document.fullscreenElement?"Exit Fullscreen":"Fullscreen";
  });

  document.addEventListener("visibilitychange",async()=>{
    if(document.visibilityState==="visible" && $("wakeButton").classList.contains("active")){
      await requestWakeLock();
    }
  });

  loadStatus();
  loadRecognition();
  setInterval(loadStatus,1800);
  setInterval(loadRecognition,650);
});
