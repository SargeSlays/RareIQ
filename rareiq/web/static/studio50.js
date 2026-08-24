
const $=id=>document.getElementById(id);

function switchWorkspace(name){
  document.querySelectorAll(".workspace").forEach(el=>el.classList.toggle("active",el.dataset.workspace===name));
  document.querySelectorAll(".nav-button").forEach(el=>el.classList.toggle("active",el.dataset.target===name));
}

function switchDock(name){
  document.querySelectorAll(".dock-tab").forEach(el=>el.classList.toggle("active",el.dataset.dock===name));
  document.querySelectorAll(".dock-panel").forEach(el=>el.classList.toggle("active",el.dataset.panel===name));
}

async function api(path,options={}){
  const response=await fetch(path,{cache:"no-store",headers:{"Content-Type":"application/json"},...options});
  return response.json();
}


let selectedCamera = null;
let cameraStreamStarted = false;

async function loadCameraList(){
  const select = $("cameraSelect");
  select.innerHTML = `<option value="">Scanning cameras…</option>`;

  try{
    const result = await api("/api/cameras");
    const cameras = result.cameras || [];

    if(!cameras.length){
      select.innerHTML = `<option value="">No cameras detected</option>`;
      selectedCamera = null;
      return;
    }

    select.innerHTML = cameras.map((camera,index)=>{
      const payload = encodeURIComponent(JSON.stringify({
        index: Number(camera.index ?? index),
        backend: Number(camera.backend ?? 700),
        name: camera.name || `Camera ${index+1}`
      }));
      const backendName = camera.backend_name
        ? ` • ${camera.backend_name}`
        : "";
      return `<option value="${payload}">${camera.name || `Camera ${index+1}`}${backendName}</option>`;
    }).join("");

    const saved = localStorage.getItem("rareiq.selectedCamera");
    if(saved && [...select.options].some(option => option.value === saved)){
      select.value = saved;
    }

    readSelectedCamera();
  }catch(error){
    select.innerHTML = `<option value="">Camera scan failed</option>`;
    selectedCamera = null;
  }
}

function readSelectedCamera(){
  const value = $("cameraSelect").value;
  if(!value){
    selectedCamera = null;
    return null;
  }

  try{
    selectedCamera = JSON.parse(decodeURIComponent(value));
    localStorage.setItem("rareiq.selectedCamera", value);
    return selectedCamera;
  }catch{
    selectedCamera = null;
    return null;
  }
}

async function selectCamera(){
  readSelectedCamera();
}

async function startSelectedCamera(){
  const camera = readSelectedCamera();
  if(!camera){
    $("cameraStatus").textContent = "SELECT A CAMERA";
    $("cameraStatus").style.color = "var(--gold)";
    return;
  }

  $("cameraStatus").textContent = "STARTING CAMERA…";
  $("cameraStatus").style.color = "var(--cyan)";

  try{
    const result = await api("/api/camera/start",{
      method:"POST",
      body:JSON.stringify({
        camera_index:Number(camera.index),
        camera_backend:Number(camera.backend)
      })
    });

    if(result.ok === false){
      throw new Error(result.error || "Camera failed to start.");
    }

    startCameraStream();
    await loadCameraStatus();
  }catch(error){
    $("cameraStatus").textContent = "CAMERA START FAILED";
    $("cameraStatus").style.color = "var(--red)";
  }
}

async function stopCamera(){
  try{
    await api("/api/camera/stop",{method:"POST",body:"{}"});
  }finally{
    $("cameraFeed").removeAttribute("src");
    cameraStreamStarted = false;
    await loadCameraStatus();
  }
}

async function reconnectCamera(){
  try{
    await api("/api/camera/stop",{method:"POST",body:"{}"});
  }catch{}
  await new Promise(resolve => setTimeout(resolve,300));
  await startSelectedCamera();
}

async function captureCamera(){
  try{
    const result = await api("/api/camera/capture",{
      method:"POST",
      body:"{}"
    });
    $("cameraStatus").textContent = result.ok
      ? "CAPTURE SAVED"
      : "NO CARD CROP";
    $("cameraStatus").style.color = result.ok
      ? "var(--green)"
      : "var(--gold)";
  }catch{
    $("cameraStatus").textContent = "CAPTURE FAILED";
    $("cameraStatus").style.color = "var(--red)";
  }
}

function startCameraStream(){
  if(cameraStreamStarted) return;
  $("cameraFeed").src = "/api/camera/stream?ts=" + Date.now();
  cameraStreamStarted = true;
}

async function loadCameraStatus(){
  try{
    const status = await api("/api/camera/status");
    const online = Boolean(status.running || status.connected);
    $("cameraStatus").textContent = online
      ? "CAMERA ONLINE"
      : "CAMERA OFFLINE";
    $("cameraStatus").style.color = online
      ? "var(--green)"
      : "var(--red)";

    if(online){
      startCameraStream();
    }
  }catch{
    $("cameraStatus").textContent = "CAMERA UNKNOWN";
    $("cameraStatus").style.color = "var(--gold)";
  }
}

async function loadRecognition(){
  try{
    const result=await api("/api/recognition-state");
    const state=result.state||result||{};
    const payload=state.payload||state.latest||{};
    const card=payload.card||payload.match||payload.current_card||null;
    const confidence=normalize(payload.confidence||payload.fused_score||0);

    $("aiState").textContent=card?"VERIFIED":"WATCHING";
    $("aiDetail").textContent=card?"Card matched against the local index.":"Place a card inside the scan zone.";
    $("confidence").textContent=`${Math.round(confidence*100)}%`;
    $("scanZone").classList.toggle("verified",Boolean(card)&&confidence>=.68);

    if(card){
      $("cardName").textContent=card.name||card.printed_name||"Recognized Card";
      $("cardMeta").textContent=[card.set_name,card.collector_number,card.language,card.rarity].filter(Boolean).join(" • ");
      const value=Number(card.market_price||card.price||0);
      $("cardValue").textContent=value>0?`$${value.toFixed(2)}`:"VALUE PENDING";
      const image=card.reference_image_url||card.local_image||"";
      if(image)$("cardArt").innerHTML=`<img src="${image}" alt="">`;
    }

    setSignal("vision",payload.visual_score||payload.artwork_score||confidence);
    setSignal("ocr",payload.ocr_score||0);
    setSignal("collector",payload.collector_score||0);
    setSignal("fusion",confidence);
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

function openProgram(){window.open("/program","rareiq-program","width=1280,height=720")}

async function maintenance(path,label){
  $("systemStatus").textContent=`${label} started…`;
  try{
    const result=await api(path,{method:"POST",body:"{}"});
    $("systemStatus").textContent=result.ok===false?(result.error||`${label} failed.`):`${label} queued.`;
  }catch{$("systemStatus").textContent=`${label} failed.`}
}

document.addEventListener("DOMContentLoaded",()=>{
  document.querySelectorAll(".nav-button").forEach(button=>button.addEventListener("click",()=>switchWorkspace(button.dataset.target)));
  document.querySelectorAll(".dock-tab").forEach(button=>button.addEventListener("click",()=>switchDock(button.dataset.dock)));
  loadCameraList();loadCameraStatus();loadRecognition();
  setInterval(loadCameraStatus,1800);
  setInterval(loadRecognition,650);
});
