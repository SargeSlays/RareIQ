
const $ = (id) => document.getElementById(id);
let activeWorkspace = "live";

function switchWorkspace(name){
  activeWorkspace = name;
  document.querySelectorAll(".workspace").forEach(el=>{
    el.classList.toggle("active", el.dataset.workspace === name);
  });
  document.querySelectorAll(".nav-button").forEach(el=>{
    el.classList.toggle("active", el.dataset.target === name);
  });
  const titles = {
    live:["Live Studio","Active ripping workspace"],
    collection:["Collection","Browse scans and session history"],
    creator:["Creator Studio","Branding, overlays, and output"],
    library:["Library Manager","Metadata, artwork, indexes, and maintenance"],
    settings:["Settings & Developer","Cameras, APIs, logs, and advanced tools"]
  };
  const [title, subtitle] = titles[name] || titles.live;
  $("workspaceTitle").textContent = title;
  $("workspaceSubtitle").textContent = subtitle;
}

async function api(path, options={}){
  const response = await fetch(path,{
    cache:"no-store",
    headers:{"Content-Type":"application/json"},
    ...options
  });
  return response.json();
}

async function loadCamera(){
  try{
    const status = await api("/api/camera/status");
    $("cameraState").textContent =
      status.running || status.connected ? "CAMERA ONLINE" : "CAMERA OFFLINE";
  }catch{
    $("cameraState").textContent = "CAMERA STATUS UNKNOWN";
  }
  $("cameraImage").src = "/api/camera/frame?ts=" + Date.now();
}

async function loadRecognition(){
  try{
    const result = await api("/api/recognition-state");
    const state = result.state || result || {};
    const payload = state.payload || state.latest || {};
    const card = payload.card || payload.match || payload.current_card || null;
    const confidence = Number(payload.confidence || payload.fused_score || 0);

    $("aiState").textContent = payload.status
      ? String(payload.status).toUpperCase()
      : card ? "VERIFIED" : "WATCHING";
    $("aiDetail").textContent = card
      ? "Card recognized and matched against the local index."
      : "Place a card inside the scan frame.";

    if(card){
      $("cardName").textContent = card.name || card.printed_name || "Recognized Card";
      $("cardMeta").textContent = [
        card.set_name,
        card.collector_number,
        card.language,
        card.rarity
      ].filter(Boolean).join(" • ");
      $("cardValue").textContent = card.market_price
        ? `$${Number(card.market_price).toFixed(2)}`
        : "VALUE PENDING";
      const image = card.reference_image_url || card.local_image || "";
      if(image){
        $("cardArt").innerHTML = `<img src="${image}" alt="">`;
      }
    }

    setSignal("vision", Number(payload.visual_score || payload.artwork_score || confidence));
    setSignal("ocr", Number(payload.ocr_score || 0));
    setSignal("collector", Number(payload.collector_score || 0));
    setSignal("fusion", confidence);

    renderSteps(payload.pipeline_stages || []);
  }catch{}
}

function setSignal(name, value){
  const normalized = value > 1 ? value / 100 : value;
  const percent = Math.max(0,Math.min(100,Math.round(normalized*100)));
  $(`${name}Bar`).style.width = `${percent}%`;
  $(`${name}Value`).textContent = `${percent}%`;
}

function renderSteps(stages){
  const normalized = new Set(
    stages.filter(stage=>stage.status==="done" || stage.done)
      .map(stage=>stage.key || stage.name)
  );
  document.querySelectorAll(".step").forEach(step=>{
    const key = step.dataset.step;
    step.classList.toggle("done", normalized.has(key));
  });
}

async function loadOverlayState(){
  const result = await api("/api/overlay/state");
  const state = result.state || {};
  $("packNumber").textContent = state.pack_number || 1;
  $("packValue").textContent = `$${Number(state.pack_total || 0).toFixed(2)}`;
  $("boxValue").textContent = `$${Number(state.box_total || 0).toFixed(2)}`;
  $("sessionValue").textContent = `$${Number(state.session_total || 0).toFixed(2)}`;
}

async function updateOverlay(patch){
  await api("/api/overlay/state",{
    method:"POST",
    body:JSON.stringify({state:patch})
  });
  await loadOverlayState();
}

async function nextPack(){
  const current = Number($("packNumber").textContent || 1);
  await updateOverlay({pack_number:current+1,pack_total:0});
}

async function resetSession(){
  await api("/api/overlay/reset",{method:"POST"});
  await loadOverlayState();
}

async function loadBrand(){
  const result = await api("/api/brand");
  const brand = result.brand || {};
  Object.entries(brand).forEach(([key,value])=>{
    const field = document.querySelector(`[data-brand="${key}"]`);
    if(field) field.value = value;
  });
  applyBrand(brand);
}

function collectBrand(){
  const settings = {};
  document.querySelectorAll("[data-brand]").forEach(field=>{
    settings[field.dataset.brand] = field.type === "number"
      ? Number(field.value)
      : field.value;
  });
  return settings;
}

function applyBrand(brand){
  const root = document.documentElement;
  const mapping = {
    background:"--bg",
    panel:"--panel",
    border:"--border",
    primary:"--primary",
    secondary:"--success",
    intelligence:"--intel",
    gold:"--gold",
    danger:"--danger",
    text:"--text",
    muted:"--muted"
  };
  Object.entries(mapping).forEach(([key,cssVar])=>{
    if(brand[key]) root.style.setProperty(cssVar,brand[key]);
  });
}

async function saveBrand(){
  const settings = collectBrand();
  const result = await api("/api/brand",{
    method:"POST",
    body:JSON.stringify({settings})
  });
  applyBrand(result.brand || settings);
  refreshPreviews();
  $("brandStatus").textContent = "Brand saved and overlays refreshed.";
}

function refreshPreviews(){
  document.querySelectorAll(".overlay-preview").forEach(frame=>{
    frame.src = frame.dataset.src + "?ts=" + Date.now();
  });
}

async function copyValue(id){
  await navigator.clipboard.writeText($(id).value);
  $("creatorStatus").textContent = "Browser source URL copied.";
}

function openProgram(){
  window.open("/program","rareiq-program","width=1280,height=720");
}

async function maintenanceAction(path,label){
  $("libraryStatus").textContent = `${label} started…`;
  try{
    const result = await api(path,{method:"POST",body:"{}"});
    $("libraryStatus").textContent = result.ok === false
      ? (result.error || `${label} failed.`)
      : `${label} queued successfully.`;
  }catch(error){
    $("libraryStatus").textContent = `${label} failed.`;
  }
}

document.addEventListener("DOMContentLoaded",()=>{
  document.querySelectorAll(".nav-button[data-target]").forEach(button=>{
    button.addEventListener("click",()=>switchWorkspace(button.dataset.target));
  });
  document.querySelectorAll("[data-brand]").forEach(field=>{
    field.addEventListener("input",()=>applyBrand(collectBrand()));
  });
  loadBrand();
  loadCamera();
  loadRecognition();
  loadOverlayState();
  setInterval(loadCamera,2000);
  setInterval(loadRecognition,700);
  setInterval(loadOverlayState,1500);
});
