
const $ = id => document.getElementById(id);
let selectedCamera = null;
let cameraStreamStarted = false;
let previousCardId = null;
let autoCaptureEnabled = true;
let captureBannerTimer = null;
let newestRecognitionGeneration = -1;
let newestRecognitionRevision = -1;
let currentServerSessionId = null;
let activityItems = [];
let cameraFitMode = "adaptive";
let cardZoomEnabled = false;
let sessionStartedAt = Date.now();
let sessionCards = 0;
let sessionHits = 0;
let sessionValue = 0;
let sessionMatches = 0;
let sessionAttempts = 0;
let cameraBootstrapRunning = false;
let cameraStreamRetryTimer = null;
let cameraStreamFailures = 0;
let cameraDiscoveryTimer = null;
let cameraStatusPollTimer = null;
let cameraAutostartComplete = false;
let cameraStartInFlight = false;
let viewerBridgeTimer = null;
let viewerBridgeConnected = false;
let viewerBridgeGeneration = 0;
let bootAutoEnterTimer = null;
let studioEntered = false;
let ui4DiagnosticsOpen = false;
let ui4HealthOpen = false;
let ui4InspectorTab = "details";
let ui4InspectorView = "current";
let ui4RecentScans = [];





function notify(title,detail="",type="info"){
  const stack=$("notificationStack");
  if(!stack) return;

  const node=document.createElement("div");
  node.className=`riq-notification ${type}`;
  node.innerHTML=`
    <div class="notification-icon">${type==="success"?"âœ“":type==="error"?"!":"â—†"}</div>
    <div class="notification-copy">
      <strong>${title}</strong>
      <span>${detail}</span>
    </div>
  `;
  stack.appendChild(node);

  setTimeout(()=>{
    node.style.opacity="0";
    node.style.transform="translateX(18px)";
    node.style.transition=".22s ease";
  },2800);
  setTimeout(()=>node.remove(),3100);
}

function updateAiPulse(state,label){
  const pulse=$("aiPulse");
  const text=$("aiPulseLabel");
  if(!pulse||!text) return;
  pulse.classList.remove("working","matched","error");

  if(state==="searching") pulse.classList.add("working");
  if(state==="matched"||state==="captured") pulse.classList.add("matched");
  if(state==="error") pulse.classList.add("error");

  text.textContent=label||(
    state==="searching"?"AI THINKING":
    state==="matched"?"MATCH FOUND":
    state==="captured"?"CAPTURED":
    state==="error"?"AI ERROR":
    "AI IDLE"
  );
}

function setCopilot(status,message){
  const badge=$("copilotBadge");
  const body=$("copilotBody");
  if(badge) badge.textContent=status;
  if(body) body.innerHTML=message;
}

function money(value){
  const amount = Number(value || 0);

  return new Intl.NumberFormat(
    "en-US",
    {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    }
  ).format(
    Number.isFinite(amount)
      ? amount
      : 0
  );
}

function updateSessionStats(){
  const elapsed=Math.max(0,Math.floor((Date.now()-sessionStartedAt)/1000));
  const minutes=Math.floor(elapsed/60);
  const seconds=elapsed%60;
  const accuracy=sessionAttempts?`${Math.round(sessionMatches/sessionAttempts*100)}%`:"â€”";

  if($("sessionCards")) $("sessionCards").textContent=String(sessionCards);
  if($("sessionHits")) $("sessionHits").textContent=String(sessionHits);
  if($("sessionValue")) $("sessionValue").textContent=money(sessionValue);
  if($("sessionAccuracy")) $("sessionAccuracy").textContent=accuracy;
  if($("sessionElapsed")) $("sessionElapsed").textContent=
    `${String(minutes).padStart(2,"0")}:${String(seconds).padStart(2,"0")}`;
  if($("emptySessionCards")) $("emptySessionCards").textContent=`${sessionCards} cards`;
}

function updateConfidenceRing(value){
  const normalized=Math.max(0,Math.min(1,Number(value||0)));
  const percent=Math.round(normalized*100);
  const ring=$("confidenceRing");
  if(ring) ring.style.setProperty("--confidence",String(percent));
  if($("confidenceRingValue")) $("confidenceRingValue").textContent=`${percent}%`;
}

function toggleShortcutOverlay(force){
  const overlay=$("shortcutOverlay");
  if(!overlay) return;
  const visible=typeof force==="boolean"?force:!overlay.classList.contains("visible");
  overlay.classList.toggle("visible",visible);
}

function shortcutBackdropClose(event){
  if(event.target===$("shortcutOverlay")) toggleShortcutOverlay(false);
}

function operatorApprove(){
  notify("Card Approved","Added to the active session.","success");
  addActivity("Card Approved","Operator approved the current candidate.");
}

function operatorReject(){
  notify("Card Rejected","Candidate removed from the active scan.","error");
  addActivity("Card Rejected","Operator rejected the current candidate.");
}

function operatorDetails(){
  notify("Card Details","Detailed card intelligence view is queued.","info");
  addActivity("Details Requested","Opening full card intelligence.");
}

function isTypingTarget(target){
  const tag=(target?.tagName||"").toLowerCase();
  return tag==="input"||tag==="textarea"||tag==="select"||target?.isContentEditable;
}

document.addEventListener("keydown",event=>{
  if(isTypingTarget(event.target)) return;

  if(event.key===" "){
    event.preventDefault();
    captureCamera();
  }else if(event.key.toLowerCase()==="a"){
    operatorApprove();
  }else if(event.key.toLowerCase()==="r"){
    operatorReject();
  }else if(event.key.toLowerCase()==="d"){
    operatorDetails();
  }else if(event.key.toLowerCase()==="p"){
    openCameraPopout();
  }else if(event.key.toLowerCase()==="z"){
    toggleCardZoom();
  }else if(event.key.toLowerCase()==="f"){
    openCameraPopout();
  }else if(event.key==="?" || (event.shiftKey&&event.key==="/")){
    toggleShortcutOverlay();
  }else if(event.key==="Escape"){
    resetUI4PresentationSurfaces();
    toggleShortcutOverlay(false);
  }
});

function applyCardZoom(enabled){
  cardZoomEnabled=Boolean(enabled);
  const workspace=document.querySelector(".camera-workspace");
  const toggle=$("cameraZoomToggle");
  if(workspace) workspace.classList.toggle("zoom-card",cardZoomEnabled);
  if(toggle) toggle.classList.toggle("active",cardZoomEnabled);
  localStorage.setItem("rareiq.cardZoom",cardZoomEnabled?"on":"off");
}

function toggleCardZoom(){
  applyCardZoom(!cardZoomEnabled);
  addActivity(
    cardZoomEnabled?"Card Zoom Enabled":"Card Zoom Disabled",
    cardZoomEnabled
      ?"Camera view enlarged for close card inspection."
      :"Camera returned to normal framing."
  );
}

function updateResolutionBadge(vision={}){
  const actual=vision.actual_resolution;
  const requested=vision.requested_resolution;
  const badge=$("resolutionBadge");
  if(!badge) return;

  if(Array.isArray(actual)&&actual.length>=2){
    const fallback=Boolean(vision.resolution_fallback);
    badge.textContent=`${actual[0]}x${actual[1]}${fallback?" FALLBACK":""}`;
    badge.classList.toggle("fallback",fallback);
    badge.title=fallback&&Array.isArray(requested)
      ? `Camera requested ${requested[0]}x${requested[1]} and supplied ${actual[0]}x${actual[1]}.`
      : `Camera input ${actual[0]}x${actual[1]}.`;
  }else{
    badge.textContent="CAMERA --";
    badge.classList.remove("fallback");
    badge.title="Waiting for the first camera frame.";
  }
}

function alignScanZone(vision={}){
  const workspace=document.querySelector(".camera-workspace");
  const feed=$("cameraFeed");
  const zone=$("scanZone");
  if(!workspace||!feed||!zone) return;

  const actual=vision.actual_resolution||[];
  const sourceWidth=Number(feed.naturalWidth||actual[0]||0);
  const sourceHeight=Number(feed.naturalHeight||actual[1]||0);
  const workspaceWidth=workspace.clientWidth;
  const workspaceHeight=workspace.clientHeight;
  if(!sourceWidth||!sourceHeight||!workspaceWidth||!workspaceHeight) return;

  const zoneValues=vision.scan_zone||{
    left:0.10,top:0.08,right:0.90,bottom:0.92
  };
  const fit=cameraFitMode==="fill"?"cover":"contain";
  const scale=fit==="cover"
    ? Math.max(workspaceWidth/sourceWidth,workspaceHeight/sourceHeight)
    : Math.min(workspaceWidth/sourceWidth,workspaceHeight/sourceHeight);
  const renderedWidth=sourceWidth*scale;
  const renderedHeight=sourceHeight*scale;
  const offsetX=(workspaceWidth-renderedWidth)/2;
  const offsetY=(workspaceHeight-renderedHeight)/2;

  zone.style.left=`${offsetX+renderedWidth*Number(zoneValues.left)}px`;
  zone.style.top=`${offsetY+renderedHeight*Number(zoneValues.top)}px`;
  zone.style.width=`${renderedWidth*(Number(zoneValues.right)-Number(zoneValues.left))}px`;
  zone.style.height=`${renderedHeight*(Number(zoneValues.bottom)-Number(zoneValues.top))}px`;
  zone.style.right="auto";
  zone.style.bottom="auto";
}

function applyCameraFit(mode){
  const valid=["adaptive","fill","frame"];
  cameraFitMode=valid.includes(mode)?mode:"adaptive";

  const workspace=document.querySelector(".camera-workspace");
  const label=$("cameraFitLabel");
  const toggle=$("cameraFitToggle");

  if(workspace){
    workspace.classList.remove("fit-adaptive","fit-fill","fit-frame","full-frame");
    workspace.classList.add(`fit-${cameraFitMode}`);
  }

  const names={
    adaptive:"ADAPTIVE",
    fill:"FILL CROP",
    frame:"FULL FRAME"
  };
  if(label) label.textContent=names[cameraFitMode];
  if(toggle) toggle.classList.toggle("active",cameraFitMode==="adaptive");

  localStorage.setItem("rareiq.cameraFitMode",cameraFitMode);
  alignScanZone(window.__rareiqVisionTelemetry||{});
}

function cycleCameraFit(){
  const order=["adaptive","fill","frame"];
  const index=order.indexOf(cameraFitMode);
  applyCameraFit(order[(index+1)%order.length]);

  const descriptions={
    adaptive:"Complete image preserved with responsive safe framing.",
    fill:"Video fills the viewport and may crop the outer edges.",
    frame:"Complete camera image shown with strict containment."
  };
  addActivity(
    `${$("cameraFitLabel").textContent} View`,
    descriptions[cameraFitMode]
  );
}

function setStateChip(id,state,label){
  const chip=$(id);
  if(!chip) return;
  chip.classList.remove("on","working","warning","error");
  if(state) chip.classList.add(state);
  const value=chip.querySelector("b");
  if(value) value.textContent=label;
}

function setRecognitionState(state,detail=""){
  const panel=$("recognitionStatePanel");
  const label=$("recognitionStateLabel");
  const detailNode=$("recognitionStateDetail");
  if(panel){
    panel.classList.remove("idle","searching","matched","captured","error");
    panel.classList.add(state);
  }
  const cameraWorkspace=document.querySelector(".camera-workspace");
  if(cameraWorkspace){
    cameraWorkspace.classList.remove(
      "state-idle","state-searching","state-matched","state-captured","state-error"
    );
    cameraWorkspace.classList.add(`state-${state}`);
  }
  if(label) label.textContent=String(state||"idle").toUpperCase();
  if(detailNode) detailNode.textContent=detail||"";
  const aiChipState =
    state==="searching" ? "working" :
    state==="matched" || state==="captured" ? "on" :
    state==="error" ? "error" : "";
  setStateChip("aiStateChip",aiChipState,String(state||"idle").toUpperCase());
  updateAiPulse(state);
}

function showCaptureBanner(success,title,detail){
  const banner=$("captureBanner");
  if(!banner) return;
  banner.classList.toggle("error",!success);
  $("captureBannerIcon").textContent=success?"âœ“":"!";
  $("captureBannerTitle").textContent=title;
  $("captureBannerDetail").textContent=detail||"";
  banner.classList.add("visible");
  clearTimeout(captureBannerTimer);
  captureBannerTimer=setTimeout(()=>banner.classList.remove("visible"),3200);
}

function addActivity(title,detail){
  const now=new Date();
  const stamp=now.toLocaleTimeString([],{
    hour:"2-digit",minute:"2-digit",second:"2-digit"
  });
  activityItems.unshift({stamp,title,detail});
  activityItems=activityItems.slice(0,4);
  const feed=$("activityFeed");
  if(!feed) return;
  feed.innerHTML=activityItems.map(item=>`
    <div class="activity-item">
      <time>${item.stamp}</time>
      <strong>${item.title}</strong>
      <span>${item.detail||""}</span>
    </div>
  `).join("");
}

function applyAutoCaptureState(enabled){
  autoCaptureEnabled=Boolean(enabled);
  const toggle=$("autoCaptureToggle");
  if(toggle) toggle.classList.toggle("on",autoCaptureEnabled);
  const label=$("autoCaptureLabel");
  if(label) label.textContent=autoCaptureEnabled?"ON":"OFF";
  if($("emptyAutoState")) $("emptyAutoState").textContent=autoCaptureEnabled?"ON":"OFF";
  setStateChip(
    "autoStateChip",
    autoCaptureEnabled?"on":"",
    autoCaptureEnabled?"ON":"OFF"
  );
}

async function toggleAutoCapture(){
  const next=!autoCaptureEnabled;
  try{
    const result=await api("/api/camera/auto-capture",{
      method:"POST",
      body:JSON.stringify({enabled:next})
    });
    const vision=result.vision||{};
    const enabled=vision.auto_capture_enabled ?? next;
    applyAutoCaptureState(enabled);
    addActivity(
      enabled?"Auto Capture Enabled":"Auto Capture Disabled",
      enabled?"RareIQ will capture stable cards automatically.":"Manual capture only."
    );
  }catch{
    showCaptureBanner(false,"AUTO CAPTURE ERROR","RareIQ could not change the setting.");
    addActivity("Auto Capture Error","Setting change failed.");
  }
}

function switchWorkspace(name){
  document.body.dataset.ui4Workspace=name;
  document.querySelectorAll(".workspace").forEach(el=>{
    el.classList.toggle("active",el.dataset.workspace===name);
  });
  document.querySelectorAll(".nav-button").forEach(el=>{
    el.classList.toggle("active",el.dataset.target===name);
  });
}

function switchDock(name){
  document.querySelectorAll(".dock-tab").forEach(el=>{
    el.classList.toggle("active",el.dataset.dock===name);
  });
  document.querySelectorAll(".dock-panel").forEach(el=>{
    el.classList.toggle("active",el.dataset.panel===name);
  });
}

function toggleDock(){
  setUI4DiagnosticsOpen(!ui4DiagnosticsOpen);
}

async function api(path,options={}){
  const response=await fetch(path,{
    cache:"no-store",
    headers:{"Content-Type":"application/json"},
    ...options
  });

  const contentType=response.headers.get("content-type")||"";
  const text=await response.text();
  let payload=null;

  if(contentType.includes("application/json")){
    try{
      payload=text?JSON.parse(text):{};
    }catch(error){
      throw new Error(`Invalid JSON from ${path}: ${error.message}`);
    }
  }else{
    const preview=text.replace(/\s+/g," ").slice(0,160);
    throw new Error(
      `API ${path} returned ${response.status} ${response.statusText} as ${contentType||"unknown content"}: ${preview}`
    );
  }

  if(!response.ok){
    throw new Error(
      payload?.message ||
      payload?.error ||
      `Request failed: ${response.status} ${response.statusText}`
    );
  }

  return payload;
}





function markViewerLive(){
  viewerBridgeConnected=true;
  cameraAutoStartDone=true;
  setCameraAutostartState("live","CAMERA LIVE");
  cameraAutostartComplete=true;
  cameraStreamStarted=true;
  cameraStreamFailures=0;

  clearTimeout(viewerBridgeTimer);
  clearTimeout(cameraStreamRetryTimer);

  const recovery=$("cameraRecovery");
  const placeholder=$("cameraPlaceholder");
  const workspace=document.querySelector(".camera-workspace");

  if(recovery){
    recovery.classList.remove("visible","success","error");
    recovery.classList.add("suppressed");
  }

  if(placeholder){
    placeholder.classList.add("hidden");
  }

  if(workspace){
    workspace.classList.add("viewer-live");
  }

  setViewerBridgeState("live","LIVE VIEWER");
}

function markViewerOffline(){
  viewerBridgeConnected=false;
  cameraStreamStarted=false;

  const recovery=$("cameraRecovery");
  const workspace=document.querySelector(".camera-workspace");

  if(workspace){
    workspace.classList.remove("viewer-live");
  }

  if(recovery){
    recovery.classList.remove("suppressed");
  }
}


let backgroundInitializationStarted=false;
let cameraAutoStartTimer=null;
let cameraAutoStartAttempts=0;
let cameraAutoStartInFlight=false;
let cameraAutoStartDone=false;
let operatorToastTimer=null;


function setCameraAutostartState(state,label){
  const chip=$("cameraAutostartChip");
  const text=$("cameraAutostartLabel");
  if(!chip||!text) return;

  chip.classList.remove("searching","starting","live","error");
  chip.classList.add(state);
  text.textContent=label;
}

function showOperatorToast(message,state="success"){
  const toast=$("operatorToast");
  if(!toast) return;

  clearTimeout(operatorToastTimer);
  toast.classList.remove("success","error");
  toast.classList.add(state,"visible");
  toast.textContent=message;

  operatorToastTimer=setTimeout(()=>{
    toast.classList.remove("visible");
  },2400);
}

function viewerHasLiveFrame(){
  const feed=$("cameraFeed");
  return Boolean(feed&&feed.naturalWidth>0&&feed.naturalHeight>0);
}

async function attemptCameraAutostart(){
  if(cameraAutoStartDone||cameraAutoStartInFlight) return;

  if(viewerHasLiveFrame()){
    cameraAutoStartDone=true;
    setCameraAutostartState("live","CAMERA LIVE");
    markViewerLive();
    return;
  }

  cameraAutoStartInFlight=true;
  cameraAutoStartAttempts+=1;
  setCameraAutostartState(
    cameraAutoStartAttempts===1?"searching":"starting",
    cameraAutoStartAttempts===1?"FINDING CAMERA":`STARTING ${cameraAutoStartAttempts}/12`
  );

  try{
    const result=await api("/api/cameras?force=true");
    const cameras=result.cameras||[];

    if(!cameras.length){
      throw new Error("No cameras detected yet.");
    }

    const select=$("cameraSelect");
    if(select){
      const saved=localStorage.getItem("rareiq.selectedCamera");
      if(saved&&[...select.options].some(option=>option.value===saved)){
        select.value=saved;
      }
    }

    let camera=readSelectedCamera();
    if(!camera){
      const first=cameras[0];
      camera={
        index:Number(first.index),
        backend:Number(first.backend),
        name:first.name||"Camera"
      };
    }

    const startResult=await api("/api/camera/start",{
      method:"POST",
      body:JSON.stringify({
        camera_index:Number(camera.index),
        camera_backend:Number(camera.backend)
      })
    });

    if(startResult?.ok===false){
      throw new Error(
        startResult?.manager?.last_error ||
        startResult?.manager?.message ||
        "Camera start failed."
      );
    }

    connectMainViewer(true);

    await delay(650);

    if(viewerHasLiveFrame()){
      cameraAutoStartDone=true;
      setCameraAutostartState("live","CAMERA LIVE");
      markViewerLive();
      showOperatorToast(`${camera.name||"Camera"} started automatically.`);
      return;
    }

    throw new Error("Waiting for first frame.");
  }catch(error){
    if(cameraAutoStartAttempts>=12){
      setCameraAutostartState("error","MANUAL START");
      showOperatorToast(
        "Camera did not auto-start. Manual Start remains available.",
        "error"
      );
      return;
    }

    clearTimeout(cameraAutoStartTimer);
    cameraAutoStartTimer=setTimeout(
      attemptCameraAutostart,
      cameraAutoStartAttempts<4?700:1400
    );
  }finally{
    cameraAutoStartInFlight=false;
  }
}

async function restartFeed(){
  cameraAutoStartDone=false;
  cameraAutoStartAttempts=0;
  cameraAutoStartInFlight=false;

  setCameraAutostartState("starting","RESTARTING FEED");
  markViewerOffline();

  try{
    await api("/api/camera/stop",{
      method:"POST",
      body:"{}"
    });
  }catch{}

  await delay(300);

  connectMainViewer(true);
  attemptCameraAutostart();
}

async function startBackgroundInitialization(){
  if(backgroundInitializationStarted) return;
  backgroundInitializationStarted=true;

  /*
  Restore the proven camera startup sequence from Studio X 6.0.3:
  1. Bootstrap the saved camera.
  2. Attach the main viewer immediately.
  3. Let First Frame Wins suppress stale loading overlays.
  */
  try{
    bootstrapCamera();
  }catch{}

  try{
    verifyAndConnectMainViewer();
  }catch{}

  setTimeout(attemptCameraAutostart,180);

  try{ loadRecognition(); }catch{}
  try{ loadSystemHealth(); }catch{}
  try{ loadCameraManagerState(); }catch{}

  setInterval(()=>loadCameraStatus({forceStream:false}),1800);
  setInterval(loadSystemHealth,5000);
  setInterval(loadCameraManagerState,1800);
}

function setViewerBridgeState(state,label){
  const node=$("viewerBridgeState");
  const text=$("viewerBridgeLabel");
  if(!node||!text) return;
  node.classList.remove("connecting","live","error");
  node.classList.add(state);
  text.textContent=label;
}

function connectMainViewer(force=false){
  const feed=$("cameraFeed");
  if(!feed) return;
  if(viewerBridgeConnected&&!force&&feed.naturalWidth>0) return;

  clearTimeout(viewerBridgeTimer);
  viewerBridgeGeneration+=1;
  viewerBridgeConnected=false;
  setViewerBridgeState("connecting","CONNECTING VIEWER");

  feed.removeAttribute("src");
  feed.src=`/api/camera/stream?viewer=main&ts=${Date.now()}&generation=${viewerBridgeGeneration}`;

  if(feed.naturalWidth>0&&feed.naturalHeight>0){
    markViewerLive();
    return;
  }

  viewerBridgeTimer=setTimeout(()=>{
    if(!(feed.naturalWidth>0&&feed.naturalHeight>0)){
      setViewerBridgeState("connecting","RETRYING VIEWER");
      connectMainViewer(true);
    }
  },1800);
}

async function verifyAndConnectMainViewer(){
  try{
    const result=await api("/api/cameras?force=false");
    if((result.cameras||[]).length){
      connectMainViewer(true);
      return true;
    }
    setViewerBridgeState("error","NO CAMERA FOUND");
    return false;
  }catch{
    setViewerBridgeState("error","VIEWER API ERROR");
    return false;
  }
}


function enterStudio(reason="ready"){
  return reason;
}

function scheduleAutomaticStudioEntry(){
  return;
}

function renderBootStatus(status){
  return status;
}

function enterStudioDegraded(){
  return;
}

async function runBootSequence(force=false){
  // Compatibility shim. Studio no longer waits on boot diagnostics.
  startBackgroundInitialization();
}

function delay(ms){
  return new Promise(resolve=>setTimeout(resolve,ms));
}

function setCameraRecovery(title,detail,state=""){
  const recovery=$("cameraRecovery");
  const feed=$("cameraFeed");
  if(!recovery) return;

  if(
    viewerBridgeConnected ||
    (feed && feed.naturalWidth>0 && feed.naturalHeight>0)
  ){
    markViewerLive();
    return;
  }

  recovery.classList.remove("success","error");
  if(state) recovery.classList.add(state);
  recovery.classList.add("visible");

  if($("cameraRecoveryTitle")) $("cameraRecoveryTitle").textContent=title;
  if($("cameraRecoveryDetail")) $("cameraRecoveryDetail").textContent=detail;
}

function hideCameraRecovery(delayMs=0){
  const recovery=$("cameraRecovery");
  if(!recovery) return;

  setTimeout(()=>{
    recovery.classList.remove("visible","success","error");
  },delayMs);
}

function cameraStatusOnline(status){
  const manager=status?.manager||{};
  const vision=status?.vision||status||{};
  return Boolean(
    manager.state==="running" &&
    manager.worker_alive===true &&
    manager.frame_fresh===true &&
    manager.stalled!==true &&
    vision.running===true &&
    !manager.last_error &&
    !vision.error
  );
}

async function waitForCameraReady(timeoutMs=15000){
  const started=Date.now();

  while(Date.now()-started<timeoutMs){
    try{
      const ready=await api("/api/camera/ready");
      if(ready.ok&&ready.frame_fresh&&ready.worker_alive){
        return ready;
      }
      setCameraRecovery(
        "Camera startingâ€¦",
        ready.message||"Waiting for the first frame."
      );
    }catch{}

    await delay(300);
  }

  return null;
}

async function ensureCameraStarted(force=false){
  if(cameraStartInFlight) return false;
  if(cameraAutostartComplete&&!force) return true;

  const camera=readSelectedCamera();
  if(!camera) return false;

  cameraStartInFlight=true;

  try{
    setCameraRecovery(
      "Starting cameraâ€¦",
      camera.name||"Opening the selected video device."
    );

    const result=await api("/api/camera/start",{
      method:"POST",
      body:JSON.stringify({
        camera_index:Number(camera.index),
        camera_backend:Number(camera.backend)
      })
    });

    if(result?.ok===false){
      throw new Error(
        result?.manager?.last_error ||
        result?.manager?.message ||
        "Camera failed to start."
      );
    }

    if(result?.already_running){
      cameraAutostartComplete=true;
    }
    cameraStreamFailures=0;
    cameraStreamStarted=false;
    startCameraStream(true);

    const ready=await waitForCameraReady();

    if(ready){
      cameraAutostartComplete=true;
      setCameraRecovery(
        "Camera online",
        ready.message||camera.name||"Live preview connected.",
        "success"
      );
      hideCameraRecovery(650);
      return true;
    }

    throw new Error("The camera manager did not receive a live frame.");
  }catch(error){
    cameraAutostartComplete=false;
    setCameraStatus("CAMERA START FAILED","var(--red)");
    setStateChip("cameraStateChip","error","FAILED");
    setCameraRecovery(
      "Camera connection failed",
      error?.message||"Use Reconnect to retry.",
      "error"
    );
    return false;
  }finally{
    cameraStartInFlight=false;
  }
}

function scheduleCameraDiscovery(){
  clearTimeout(cameraDiscoveryTimer);

  cameraDiscoveryTimer=setTimeout(async()=>{
    if(cameraAutostartComplete) return;

    const cameras=await loadCameraList({
      retries:1,
      delay:450,
      silent:true
    });

    if(cameras.length){
      await ensureCameraStarted();
    }

    if(!cameraAutostartComplete){
      scheduleCameraDiscovery();
    }
  },1600);
}

async function loadCameraList(options={}){
  const {retries=5,delay=650,silent=false}=options;
  const select=$("cameraSelect");
  if(!silent) select.innerHTML=`<option value="">Scanning camerasâ€¦</option>`;

  for(let attempt=0;attempt<=retries;attempt+=1){
    try{
      const result=await api("/api/cameras");
      const cameras=result.cameras||[];
      if(cameras.length){
        select.innerHTML=cameras.map((camera,index)=>{
          const payload=encodeURIComponent(JSON.stringify({
            index:Number(camera.index??index),
            backend:Number(camera.backend??700),
            name:camera.name||`Camera ${index+1}`
          }));
          const backendName=camera.backend_name?` â€¢ ${camera.backend_name}`:"";
          return `<option value="${payload}">${camera.name||`Camera ${index+1}`}${backendName}</option>`;
        }).join("");

        const saved=localStorage.getItem("rareiq.selectedCamera");
        if(saved&&[...select.options].some(option=>option.value===saved)){
          select.value=saved;
        }
        readSelectedCamera();
        return cameras;
      }
    }catch{}

    if(attempt<retries){
      select.innerHTML=`<option value="">Camera scan retry ${attempt+1}/${retries}â€¦</option>`;
      await new Promise(resolve=>setTimeout(resolve,delay));
    }
  }

  select.innerHTML=`<option value="">No cameras detected â€” Refresh to retry</option>`;
  selectedCamera=null;
  return [];
}

function readSelectedCamera(){
  const value = $("cameraSelect").value;
  if(!value){
    selectedCamera = null;
    return null;
  }
  try{
    selectedCamera = JSON.parse(decodeURIComponent(value));
    localStorage.setItem("rareiq.selectedCamera",value);
    return selectedCamera;
  }catch{
    selectedCamera = null;
    return null;
  }
}

async function selectCamera(){
  readSelectedCamera();
  cameraAutostartComplete=false;
  ensureCameraStarted(true);
}

async function startSelectedCamera(){
  const camera=readSelectedCamera();

  if(!camera){
    setCameraStatus("SELECT A CAMERA","var(--gold)");
    return;
  }

  cameraAutostartComplete=false;
  await ensureCameraStarted(true);
}

async function stopCamera(){
  try{
    await api("/api/camera/stop",{method:"POST",body:"{}"});
  }finally{
    $("cameraFeed").removeAttribute("src");
    const placeholder = $("cameraPlaceholder");
    if(placeholder) placeholder.classList.remove("hidden");
    cameraStreamStarted=false;
    await loadCameraStatus();
  }
}

async function reconnectCamera(){
  cameraAutostartComplete=false;
  cameraStreamStarted=false;
  cameraStreamFailures=0;

  setCameraRecovery(
    "Recovering cameraâ€¦",
    "The backend Camera Manager is reopening the saved device."
  );

  try{
    const result=await api("/api/camera/recover",{
      method:"POST",
      body:"{}"
    });

    if(result?.ok===false){
      throw new Error(
        result?.manager?.last_error ||
        result?.manager?.message ||
        "Recovery failed."
      );
    }

    startCameraStream(true);
    const ready=await waitForCameraReady();

    if(!ready){
      throw new Error("No frame arrived after recovery.");
    }

    cameraAutostartComplete=true;
    hideCameraRecovery(500);
  }catch(error){
    setCameraRecovery(
      "Recovery failed",
      error?.message||"Camera Manager could not restore the feed.",
      "error"
    );
  }
}

async function captureCamera(){
  setRecognitionState("searching","Saving current corrected card cropâ€¦");
  try{
    const result=await api("/api/camera/capture",{
      method:"POST",
      body:"{}"
    });

    if(result.ok && (result.job_accepted || result.queued)){
      const file=result.path ? String(result.path).split(/[\/]/).pop() : "Capture saved";
      const queued=Boolean(result.queued);
      setCameraStatus(queued?"RECOGNITION QUEUED":"RECOGNITION ACCEPTED","var(--green)");
      setRecognitionState("captured",queued?"Fresh crop queued for recognition.":"Fresh crop submitted for recognition.");
      showCaptureBanner(true,queued?"RECOGNITION QUEUED":"RECOGNITION ACCEPTED",file);
      notify(queued?"Recognition Queued":"Recognition Accepted",file,"success");
      addActivity("Manual Capture",`${file} / generation ${result.generation}`);
    }else if(result.ok){
      setCameraStatus("CROP SAVED / JOB REJECTED","var(--gold)");
      setRecognitionState("error",result.reason||"Recognition job was not accepted.");
      showCaptureBanner(false,"JOB NOT ACCEPTED",result.reason||"Crop saved only.");
    }else{
      setCameraStatus("NO CARD CROP","var(--gold)");
      setRecognitionState("error","No corrected card image is available yet.");
      showCaptureBanner(false,"CAPTURE NOT SAVED",result.error||"No corrected card crop available.");
      notify("Capture Not Saved",result.error||"No corrected crop.","error");
      addActivity("Capture Failed",result.error||"No corrected crop.");
    }
  }catch{
    setCameraStatus("CAPTURE FAILED","var(--red)");
    setRecognitionState("error","Capture request failed.");
    showCaptureBanner(false,"CAPTURE FAILED","RareIQ could not save the card.");
    addActivity("Capture Failed","Request error.");
  }
}

function startCameraStream(force=false){ connectMainViewer(force); }

function __oldStartCameraStream(force=false){
  const feed=$("cameraFeed");
  if(!feed) return;
  if(cameraStreamStarted&&!force&&feed.getAttribute("src")) return;

  clearTimeout(cameraStreamRetryTimer);
  const placeholder=$("cameraPlaceholder");
  const recovery=$("cameraRecovery");

  if(recovery){
    recovery.classList.add("visible");
    $("cameraRecoveryTitle").textContent="Connecting cameraâ€¦";
    $("cameraRecoveryDetail").textContent="Waiting for the first live frame.";
  }

  feed.src=`/api/camera/stream?ts=${Date.now()}&retry=${cameraStreamFailures}`;
  cameraStreamStarted=true;

  cameraStreamRetryTimer=setTimeout(()=>{
    const hasFrame=feed.naturalWidth>0&&feed.naturalHeight>0;
    if(!hasFrame){
      cameraStreamStarted=false;
      cameraStreamFailures+=1;
      if(cameraStreamFailures<=8){
        if(recovery){
          recovery.classList.add("visible");
          $("cameraRecoveryTitle").textContent="Restoring live previewâ€¦";
          $("cameraRecoveryDetail").textContent=`Retry ${cameraStreamFailures} of 8`;
        }
        startCameraStream(true);
      }else{
        if(placeholder) placeholder.classList.remove("hidden");
        if(recovery){
          recovery.classList.add("visible");
          $("cameraRecoveryTitle").textContent="Live preview unavailable";
          $("cameraRecoveryDetail").textContent="Use Reconnect or Refresh Camera.";
        }
      }
    }
  },1400);
}

function setCameraStatus(text,color){
  $("cameraStatus").textContent=text;
  $("cameraStatus").style.color=color;
}


async function bootstrapCamera(){
  if(cameraBootstrapRunning) return;
  cameraBootstrapRunning=true;
  cameraAutostartComplete=false;

  try{
    setCameraRecovery(
      "Discovering camerasâ€¦",
      "RareIQ is scanning Windows video devices."
    );

    const cameras=await loadCameraList({
      retries:10,
      delay:700
    });

    if(!cameras.length){
      setCameraStatus("CAMERA NOT FOUND","var(--gold)");
      setStateChip("cameraStateChip","warning","SEARCHING");
      setCameraRecovery(
        "Waiting for cameraâ€¦",
        "RareIQ will continue checking automatically."
      );
      scheduleCameraDiscovery();
      return;
    }

    const started=await ensureCameraStarted(true);

    if(!started){
      scheduleCameraDiscovery();
    }
  }finally{
    cameraBootstrapRunning=false;
  }
}

async function loadCameraStatus(options={}){
  const {forceStream=false}=options;
  try{
    const status = await api("/api/camera/status");
    const manager=status.manager||{};
    const vision=status.vision||status;
    const online=cameraStatusOnline(status);
    const stalled=Boolean(
      manager.stalled ||
      manager.state==="stalled" ||
      manager.health_reason==="frame_progress_stalled"
    );
    setCameraStatus(
      online ? "CAMERA ONLINE" : (stalled ? "CAMERA STALLED" : "CAMERA OFFLINE"),
      online ? "var(--green)" : "var(--red)"
    );
    setStateChip(
      "cameraStateChip",
      online?"on":(stalled?"warning":"error"),
      online?"ONLINE":(stalled?"STALLED":"OFFLINE")
    );
    applyAutoCaptureState(vision.auto_capture_enabled ?? true);
    window.__rareiqVisionTelemetry=vision;
    updateResolutionBadge(vision);
    alignScanZone(vision);
    const feed=$("cameraFeed");
    const viewerHasFrame=Boolean(feed&&feed.naturalWidth>0&&feed.naturalHeight>0);

    if(viewerHasFrame){
      markViewerLive();
      alignScanZone(window.__rareiqVisionTelemetry||{});
    }else if(online){
      if(forceStream||!cameraStreamStarted){
        startCameraStream(forceStream);
      }
    }else if(!cameraStartInFlight){
      setStateChip("cameraStateChip","warning","STARTING");
    }

    if(vision.fps){
      $("fpsValue").textContent = `${Math.round(Number(vision.fps))} FPS`;
    }
  }catch{
    if(!cameraStartInFlight&&!cameraAutostartComplete){
      setCameraStatus("CAMERA STATUS RETRYING","var(--gold)");
    }
  }
}

function normalize(value){
  const number=Number(value||0);
  return Math.max(0,Math.min(1,number>1?number/100:number));
}

function setSignal(name,value){
  const percent=Math.round(normalize(value)*100);
  const bar=$(`${name}Bar`);
  const text=$(`${name}Value`);
  const hudBar=$(`${name}HudBar`);
  const hudText=$(`${name}HudValue`);
  if(bar) bar.style.width=`${percent}%`;
  if(text) text.textContent=`${percent}%`;
  if(hudBar) hudBar.style.width=`${percent}%`;
  if(hudText) hudText.textContent=`${percent}%`;
}

const PIPELINE_STAGE_DEFINITIONS=[
  {key:"detect",label:"Detect",aliases:["detect","detection","visible","card_detected"]},
  {key:"stabilize",label:"Stabilize",aliases:["stabilize","acquiring","stable","lock","card_locked"]},
  {key:"capture",label:"Capture",aliases:["capture","prepare","crop","card_captured"]},
  {key:"recognize",label:"Recognize",aliases:["recognize","read","ocr","searching","recognition"]},
  {key:"match",label:"Match",aliases:["match","artwork","verify","verified","candidate"]}
];
const PIPELINE_STATES=["waiting","active","complete","warning","failed","skipped"];
const PIPELINE_STATE_LABELS={
  waiting:"Waiting",active:"Active",complete:"Complete",
  warning:"Warning",failed:"Failed",skipped:"Skipped"
};
const PIPELINE_STATE_ICONS={
  waiting:"•",active:"▶",complete:"✓",warning:"!",failed:"×",skipped:"–"
};

function normalizePipelineState(stage){
  if(!stage||typeof stage!=="object") return "waiting";
  const raw=String(stage.status??stage.state??"").trim().toLowerCase();
  if(stage.failed===true||stage.error===true||["error","failed","failure"].includes(raw)) return "failed";
  if(stage.warning===true||["warning","warn","degraded"].includes(raw)) return "warning";
  if(stage.skipped===true||["skipped","skip","not_applicable"].includes(raw)) return "skipped";
  if(stage.done===true||["done","complete","completed","success","succeeded"].includes(raw)) return "complete";
  if(stage.active===true||["running","active","working","processing","in_progress"].includes(raw)) return "active";
  if(["idle","pending","waiting","queued",""].includes(raw)) return "waiting";
  return "waiting";
}

function renderPipeline(stages,hasCard){
  const sourceStages=Array.isArray(stages)?stages:[];
  const normalizedStages=sourceStages.map(stage=>({
    key:String(stage?.key??stage?.name??"").trim().toLowerCase(),
    state:normalizePipelineState(stage)
  }));
  const precedence={failed:6,warning:5,active:4,complete:3,skipped:2,waiting:1};
  let activeClaimed=false;

  document.querySelectorAll(".pipeline-step").forEach((el,index)=>{
    const definition=PIPELINE_STAGE_DEFINITIONS[index];
    const matches=normalizedStages.filter(stage=>definition.aliases.includes(stage.key));
    let state=matches.reduce(
      (selected,stage)=>precedence[stage.state]>precedence[selected]?stage.state:selected,
      "waiting"
    );
    if(hasCard&&!matches.length) state="complete";
    if(state==="active"){
      if(activeClaimed) state="waiting";
      else activeClaimed=true;
    }

    PIPELINE_STATES.forEach(value=>el.classList.remove(`state-${value}`));
    el.classList.remove("active","done");
    el.classList.add(`state-${state}`);
    el.classList.toggle("active",state==="active");
    el.classList.toggle("done",state==="complete");
    el.dataset.state=state;
    if(state==="active") el.setAttribute("aria-current","step");
    else el.removeAttribute("aria-current");

    const status=PIPELINE_STATE_LABELS[state];
    const statusNode=el.querySelector(".process-status b");
    const icon=el.querySelector(".process-state-icon");
    if(statusNode) statusNode.textContent=status;
    if(icon) icon.textContent=PIPELINE_STATE_ICONS[state];
    el.setAttribute("aria-label",`${definition.label}: ${status}`);
  });
}

function setScanState(payload,card,confidence){
  const zone=$("scanZone");
  const status=String(payload.status||"").toLowerCase();

  zone.classList.remove("detected","reading","verified");
  if(card && confidence>=.68){
    zone.classList.add("verified");
  }else if(status.includes("ocr")||status.includes("read")){
    zone.classList.add("reading");
  }else if(status.includes("detect")||payload.card_detected){
    zone.classList.add("detected");
  }
}

function triggerHit(){
  document.body.classList.remove("hit-flash");
  void document.body.offsetWidth;
  document.body.classList.add("hit-flash");
  $("scanZone").classList.add("hit");
  setTimeout(()=>$("scanZone").classList.remove("hit"),1000);
}


function setCoreState(state){
  const orb = $("coreOrb");
  const label = $("coreLabel");
  if(!orb || !label) return;
  orb.classList.remove("scanning","matched","complete");
  const normalized = String(state||"idle").toLowerCase();
  if(normalized==="scanning" || normalized==="processing"){
    orb.classList.add("scanning");
    label.textContent="SCANNING";
  }else if(normalized==="matched" || normalized==="verified"){
    orb.classList.add("matched");
    label.textContent="MATCH FOUND";
  }else if(normalized==="complete"){
    orb.classList.add("complete");
    label.textContent="COMPLETE";
  }else{
    label.textContent="IDLE";
  }
}

function resetRecognitionPresentation(reason="reset"){
  resetUI4PresentationSurfaces();
  previousCardId=null;
  const empty=$("inspectorEmpty");
  const main=$("inspectorMain");
  if(empty) empty.style.display="grid";
  if(main) main.style.display="none";
  if($("cardArt")) $("cardArt").innerHTML="";
  if($("cardName")) $("cardName").textContent="Waiting for card";
  if($("cardMeta")) $("cardMeta").textContent="";
  if($("cardStatus")) $("cardStatus").textContent="SEARCHING";
  if($("confidence")) $("confidence").textContent="0%";
  updateConfidenceRing(0);
  setSignal("vision",0);
  setSignal("ocr",0);
  setSignal("collector",0);
  setSignal("fusion",0);
  renderPipeline([],false);
  setCoreState("idle");
  window.__rareiqRecognitionPoll={
    revision:null,
    generation:null,
    serverSessionId:currentServerSessionId,
    phase:"EMPTY",
    candidateCount:0,
    resetReason:reason,
    updatedAt:Date.now(),
  };
}

async function loadRecognition(){
  try{
    const result = await api(
      `/api/recognition-state?t=${Date.now()}`
    );

    const snapshot =
      result?.recognition_state ||
      result?.state ||
      result?.snapshot ||
      result ||
      {};

    const serverSessionId=String(
      result?.server_session_id ??
      snapshot?.server_session_id ??
      ""
    );
    if(serverSessionId && serverSessionId!==currentServerSessionId){
      const hadPreviousSession=currentServerSessionId!==null;
      currentServerSessionId=serverSessionId;
      newestRecognitionGeneration=-1;
      newestRecognitionRevision=-1;
      resetRecognitionPresentation(
        hadPreviousSession ? "server_session_changed" : "server_session_initialized"
      );
      setUI4InspectorView("current",false);
    }

    const generation=Number(snapshot?.generation ?? 0);
    const revision=Number(snapshot?.revision ?? 0);
    if(
      generation < newestRecognitionGeneration ||
      (generation === newestRecognitionGeneration && revision < newestRecognitionRevision)
    ){
      return;
    }
    newestRecognitionGeneration=Math.max(newestRecognitionGeneration,generation);
    newestRecognitionRevision=revision;

    const raw =
      snapshot?.raw_recognition ||
      snapshot?.payload ||
      snapshot?.latest ||
      {};

    const candidates = Array.isArray(snapshot?.candidates)
      ? snapshot.candidates
      : Array.isArray(raw?.candidates)
      ? raw.candidates
      : [];

    const identityAgrees = candidate => {
      const signals = candidate?.signals || {};
      return Number(signals.ocr_name || 0) >= 0.75 ||
        Number(signals.collector_number || 0) >= 1;
    };

    const realIdentityCandidate =
      candidates.find(
        candidate =>
          candidate &&
          candidate.source !== "ocr_provisional" &&
          ["database", "live_catalog", "catalog"].includes(
            String(candidate.source || "").toLowerCase()
          ) &&
          (
            candidate.image_path ||
            candidate.reference_image ||
            candidate.local_image ||
            candidate.reference_image_url
          )
      ) || null;

    const verifiedVisualCandidate =
      candidates.find(
        candidate =>
          candidate &&
          candidate.source !== "ocr_provisional" &&
          candidate.verification_strong === true &&
          identityAgrees(candidate)
      ) || null;

    let card =
      realIdentityCandidate ||
      verifiedVisualCandidate ||
      snapshot.primary_candidate ||
      snapshot.provisional_candidate ||
      {};

    const phase = String(
      snapshot?.continuous_state ||
      snapshot?.phase ||
      raw?.status ||
      snapshot?.verification_state ||
      "IDLE"
    ).toUpperCase();

    const clearInspector = ["EMPTY", "CHANGING"].includes(phase) ||
      (phase === "LOST" && !snapshot?.card_present);
    if(clearInspector){
      snapshot.primary_candidate=null;
      snapshot.provisional_candidate=null;
      candidates.length=0;
      card=null;
      resetRecognitionPresentation("backend_empty");
    }

    const confidence = normalize(
      card?.fused_score ??
      card?.score ??
      card?.confidence ??
      (
        card === snapshot?.primary_candidate
          ? snapshot?.overall_confidence ?? snapshot?.confidence
          : 0
      ) ??
      raw?.fused_score ??
      raw?.confidence ??
      0
    );

    const locked = Boolean(
      snapshot?.recognition_locked ||
      raw?.recognition_locked
    );

    const hasCandidate = Boolean(
      card ||
      snapshot?.provisional_candidate ||
      candidates.length
    );

    const verified = Boolean(
      realIdentityCandidate ||
      verifiedVisualCandidate
    );

    $("aiState").textContent = verified
      ? "VERIFIED"
      : hasCandidate
      ? "CANDIDATE"
      : phase === "IDLE"
      ? "WATCHING"
      : phase;

    setCoreState(
      verified
        ? "matched"
        : phase === "IDLE"
        ? "idle"
        : "scanning"
    );

    if(phase === "CHANGING"){
      setRecognitionState("searching","Card change detected. Acquiring the new card.");
      setCopilot("CHANGING","RareIQ invalidated the previous result and is acquiring the replacement card.");
    }else if(phase === "RECOGNIZING"){
      setRecognitionState("searching","Recognizing the current card.");
      setCopilot("RECOGNIZING","RareIQ is processing the newest card generation.");
    }else if(verified && card){
      setRecognitionState(
        "matched",
        "Database match verified."
      );

      setCopilot(
        "VERIFIED",
        `RareIQ verified <b>${
          card.name ||
          card.english_name ||
          card.printed_name ||
          "this card"
        }</b> at ${Math.round(confidence*100)}% confidence.`
      );
    }else if(hasCandidate){
      setRecognitionState(
        "searching",
        `${phase.replaceAll("_"," ")} â€¢ ${
          candidates.length || snapshot?.candidate_count || 1
        } candidate${(
          candidates.length ||
          snapshot?.candidate_count ||
          1
        ) === 1 ? "" : "s"}`
      );

      setCopilot(
        "ANALYZING",
        `RareIQ found reference evidence and is verifying the strongest candidate.`
      );
    }else if(phase !== "IDLE"){
      setRecognitionState(
        "searching",
        phase.replaceAll("_"," ")
      );

      setCopilot(
        "ANALYZING",
        `RareIQ is <b>${phase.replaceAll("_"," ").toLowerCase()}</b>. Visual, OCR, and database signals are being fused.`
      );
    }else{
      setRecognitionState(
        "idle",
        "Waiting for a card."
      );

      updateConfidenceRing(0);

      setCopilot(
        "STANDBY",
        "Place a card in the scan zone. RareIQ will identify, verify, and explain what it finds."
      );
    }

    $("aiDetail").textContent = verified
      ? "Card verified against the active artwork index."
      : hasCandidate
      ? `${candidates.length || snapshot?.candidate_count || 1} candidate result${
          (candidates.length || snapshot?.candidate_count || 1) === 1
            ? ""
            : "s"
        } available.`
      : "Place a card inside the scan zone.";

    $("confidence").textContent =
      `${Math.round(confidence*100)}%`;

    const uiPayload = {
      ...raw,
      ...snapshot,
      status: phase,
      candidates,
      card,
      confidence,
      fused_score: confidence,
      pipeline_stages:
        snapshot?.pipeline_stages ||
        raw?.pipeline_stages ||
        [],
      latency_ms:
        snapshot?.stage_timings?.total_ms ??
        raw?.latency_ms ??
        0,
    };

    setScanState(
      uiPayload,
      card,
      confidence
    );

    const vision =
      snapshot?.artwork_index?.score ??
      card?.visual_score ??
      card?.artwork_score ??
      raw?.visual_score ??
      raw?.artwork_score ??
      confidence;

    const ocr =
      card?.ocr_score ??
      raw?.ocr_score ??
      0;

    const collector =
      card?.collector_score ??
      raw?.collector_score ??
      0;

    setSignal("vision",vision);
    setSignal("ocr",ocr);
    setSignal("collector",collector);
    setSignal("fusion",confidence);

    const empty = $("inspectorEmpty");
    const main = $("inspectorMain");

    if(card && !clearInspector){
      if(empty) empty.style.display="none";
      if(main) main.style.display="grid";

      const cardId =
        card.id ||
        `${card.set_id||""}:${card.collector_number||""}:${
          card.name ||
          card.english_name ||
          card.printed_name ||
          ""
        }`;

      const rawCardName = String(
        card.english_name ||
        card.printed_name ||
        card.name ||
        ""
      ).trim();

      const setId = String(
        card.set_id ||
        card.set_name ||""
      ).trim();

      const collectorNumber = String(
        card.collector_number ||
        ""
      ).trim();

      const looksLikeFilename =
        rawCardName.length > 70 ||
        rawCardName.includes("-Set-List-") ||
        rawCardName.includes("-Pokemon-") ||
        rawCardName.includes("-Pokipair-") ||
        rawCardName.includes("-Store-") ||
        /\.(jpg|jpeg|png|webp|avif)$/i.test(
          rawCardName
        );

      $("cardName").textContent =
        looksLikeFilename || !rawCardName
          ? [
              "Unidentified",
              setId,
              collectorNumber
                ? `Card ${collectorNumber}`
                : "Card"
            ]
              .filter(Boolean)
              .join(" ")
          : rawCardName;

      $("cardMeta").textContent = [
        card.set_name,
        card.collector_number ||
          snapshot?.collector_number,
        card.language ||
          snapshot?.language,
        card.rarity,
        verified
          ? "VERIFIED"
          : "PROVISIONAL"
      ].filter(Boolean).join(" â€¢ ");

      const rawValue = Number(
        card.market_price ||
        card.price ||
        0
      );

      const psa10 = Number(
        card.psa10_price ||
        0
      );

      const population = Number(
        card.population ||
        card.psa10_population ||
        0
      );

      $("cardValue").textContent =
        rawValue > 0
          ? `$${rawValue.toFixed(2)}`
          : "VALUE PENDING";

      $("rawValue").textContent =
        rawValue > 0
          ? `$${rawValue.toFixed(2)}`
          : "â€”";

      $("psaValue").textContent =
        psa10 > 0
          ? `$${psa10.toFixed(2)}`
          : "â€”";

      $("populationValue").textContent =
        population > 0
          ? String(population)
          : "â€”";

      $("cardStatus").textContent = verified
        ? "VERIFIED DATABASE MATCH"
        : confidence >= .68
        ? "CANDIDATE MATCH"
        : "REVIEW REQUIRED";

      const localImage =
        card.image_path ||
        card.reference_image ||
        card.local_image ||
        "";

      const image =
       card.reference_image_url ||
       card.image_url ||
       (
         localImage
           ? "/api/reference-image?path="
             + encodeURIComponent(
                 String(localImage)
               )
            : ""
      );

      if(image){
        const source = String(image).replaceAll("\\","/");
        $("cardArt").innerHTML =
          `<img src="${source}" alt="">`;
      }

      if(
        verified &&
        cardId &&
        cardId !== previousCardId
      ){
        sessionCards += 1;
        sessionAttempts += 1;
        sessionMatches += 1;
        sessionValue += rawValue;

        if(rawValue >= 100){
          sessionHits += 1;
        }

        updateSessionStats();

        addActivity(
          "Match Found",
          `${
            card.name ||
            card.english_name ||
            card.printed_name ||
            "Card"
          } â€¢ ${Math.round(confidence*100)}%`
        );

        notify(
          rawValue >= 100
            ? "High-Value Match"
            : "Match Found",
          `${
            card.name ||
            card.english_name ||
            card.printed_name ||
            "Card"
          } â€¢ ${Math.round(confidence*100)}%`,
          "success"
        );

        if(
          previousCardId &&
          rawValue >= 100
        ){
          triggerHit();
      }
    }else if(clearInspector){
      if(empty) empty.style.display="grid";
      if(main) main.style.display="none";
      $("cardName").textContent="Waiting for card";
      $("cardMeta").textContent="";
      $("cardArt").innerHTML="";
      updateConfidenceRing(0);
    }

      if(verified){
        previousCardId = cardId;
      }
    }else{
      if(empty) empty.style.display="grid";
      if(main) main.style.display="none";
    }

    renderPipeline(
      uiPayload.pipeline_stages,
      verified
    );

    $("latencyValue").textContent =
      uiPayload.latency_ms
        ? `${Math.round(Number(uiPayload.latency_ms))} ms`
        : phase === "IDLE"
        ? "Idle"
        : "Active";

    $("cardsValue").textContent =
      String(
        snapshot?.session_cards ||
        raw?.session_cards ||
        0
      );

    $("hitsValue").textContent =
      String(
        snapshot?.session_hits ||
        raw?.session_hits ||
        0
      );

    window.__rareiqRecognitionPoll = {
      serverSessionId:currentServerSessionId,
      generation: snapshot?.generation ?? null,
      revision: snapshot?.revision ?? null,
      phase,
      candidateCount:
        candidates.length ||
        snapshot?.candidate_count ||
        0,
      updatedAt: Date.now(),
    };
  }catch(error){
    console.warn(
      "RareIQ recognition poll failed",
      error
    );

    setRecognitionState(
      "error",
      "Recognition state unavailable."
    );
  }
}


async function loadSystemHealth(){
  try{
    const result=await api("/api/system/health");
    const components=result.components||{};

    Object.entries(components).forEach(([name,component])=>{
      const card=document.querySelector(`[data-health="${name}"]`);
      if(!card) return;

      card.classList.toggle("healthy",Boolean(component.healthy));
      card.classList.toggle("error",!component.healthy);

      const state=card.querySelector("strong");
      const message=card.querySelector("p");
      if(state) state.textContent=String(component.state||"unknown").toUpperCase();
      if(message) message.textContent=component.message||"No status message.";
    });
  }catch{}
}

async function loadCameraManagerState(){
  try{
    const status=await api("/api/camera/status");
    const manager=status.manager||{};
    const node=$("cameraManagerState");
    if(node){
      node.textContent=[
        `STATE: ${String(manager.state||"unknown").toUpperCase()}`,
        `GENERATION: ${manager.generation??0}`,
        `CACHED DEVICES: ${manager.cached_devices??0}`,
        `RECOVERIES: ${manager.recovery_count??0}`,
        `MESSAGE: ${manager.message||"None"}`
      ].join("  â€¢  ");
    }
  }catch{}
}

function openCameraPopout(){
  const width=Math.min(1280,window.screen.availWidth||1280);
  const height=Math.min(820,window.screen.availHeight||820);
  window.open(
    "/camera-popout",
    "rareiq-camera-popout",
    `popup=yes,width=${width},height=${height},resizable=yes,scrollbars=no`
  );
}

function openProgram(){
  window.open("/program","rareiq-program","width=1280,height=720");
}

async function maintenance(path,label){
  $("systemStatus").textContent=`${label} startedâ€¦`;
  try{
    const result=await api(path,{method:"POST",body:"{}"});
    $("systemStatus").textContent=result.ok===false
      ? (result.error||`${label} failed.`)
      : `${label} queued.`;
  }catch{
    $("systemStatus").textContent=`${label} failed.`;
  }
}

function setUI4DiagnosticsOpen(open){
  ui4DiagnosticsOpen=Boolean(open);
  const drawer=document.querySelector(".ui4-diagnostics-drawer");
  if(drawer){
    drawer.classList.toggle("open",ui4DiagnosticsOpen);
    drawer.setAttribute("aria-hidden",ui4DiagnosticsOpen?"false":"true");
  }
  const trigger=document.querySelector('[data-ui4-action="diagnostics"]');
  if(trigger) trigger.setAttribute("aria-expanded",ui4DiagnosticsOpen?"true":"false");
  if($("dockToggle")) $("dockToggle").textContent="Close";
}

function setUI4HealthOpen(open){
  ui4HealthOpen=Boolean(open);
  const popover=document.querySelector(".ui4-health-popover");
  if(popover){
    popover.classList.toggle("open",ui4HealthOpen);
    popover.setAttribute("aria-hidden",ui4HealthOpen?"false":"true");
  }
  const trigger=document.querySelector('[data-ui4-action="health"]');
  if(trigger) trigger.setAttribute("aria-expanded",ui4HealthOpen?"true":"false");
}

function setUI4InspectorTab(name){
  ui4InspectorTab=name||"details";
  document.querySelectorAll("[data-inspector-tab]").forEach(button=>{
    const selected=button.dataset.inspectorTab===ui4InspectorTab;
    button.classList.toggle("active",selected);
    button.setAttribute("aria-selected",selected?"true":"false");
    button.tabIndex=selected?0:-1;
  });
  document.querySelectorAll("[data-inspector-panel]").forEach(panel=>{
    panel.hidden=panel.dataset.inspectorPanel!==ui4InspectorTab;
  });
}

function resetUI4PresentationSurfaces(){
  setUI4DiagnosticsOpen(false);
  setUI4HealthOpen(false);
  setUI4InspectorTab("details");
}

function recentScanConfidence(value){
  const numeric=Number(value||0);
  return Math.round(Math.max(0,Math.min(100,numeric<=1?numeric*100:numeric)));
}

function renderUI4RecentScanDetail(card){
  const view=document.querySelector(".ui4-recent-scans-view");
  if(!view) return;
  view.replaceChildren();
  const back=document.createElement("button");
  back.type="button";
  back.className="ui4-history-back";
  back.textContent="Back to Recent Scans";
  back.addEventListener("click",()=>renderUI4RecentScans(ui4RecentScans));
  const detail=document.createElement("article");
  detail.className="ui4-history-detail";
  if(card.reference_image_url){
    const image=document.createElement("img");
    image.src=card.reference_image_url;
    image.alt="";
    detail.appendChild(image);
  }
  const name=document.createElement("h3");
  name.textContent=card.card_name||card.printed_name||"Unknown card";
  const meta=document.createElement("p");
  meta.textContent=[card.set_name,card.collector_number].filter(Boolean).join(" • ")||"Set details unavailable";
  const confidence=document.createElement("strong");
  confidence.textContent=`${recentScanConfidence(card.confidence)}% confidence`;
  const stamp=document.createElement("time");
  stamp.textContent=card.timestamp?new Date(Number(card.timestamp)*1000).toLocaleString():"Time unavailable";
  detail.append(name,meta,confidence,stamp);
  const live=document.createElement("button");
  live.type="button";
  live.className="ui4-return-live";
  live.textContent="Return to Live Card";
  live.addEventListener("click",()=>setUI4InspectorView("current",false));
  view.append(back,detail,live);
}

function renderUI4RecentScans(cards=[]){
  const view=document.querySelector(".ui4-recent-scans-view");
  if(!view) return;
  ui4RecentScans=[...cards]
    .sort((left,right)=>Number(right.timestamp||0)-Number(left.timestamp||0))
    .slice(0,20);
  view.replaceChildren();
  if(!ui4RecentScans.length){
    const empty=document.createElement("div");
    empty.className="ui4-history-empty";
    const title=document.createElement("strong");
    title.textContent="No recent scans";
    const copy=document.createElement("span");
    copy.textContent="Completed cards from this session will appear here.";
    empty.append(title,copy);
    view.appendChild(empty);
    return;
  }
  const list=document.createElement("div");
  list.className="ui4-history-list";
  ui4RecentScans.forEach(card=>{
    const row=document.createElement("button");
    row.type="button";
    row.className="ui4-history-row";
    row.addEventListener("click",()=>renderUI4RecentScanDetail(card));
    const thumb=document.createElement("span");
    thumb.className="ui4-history-thumb";
    if(card.reference_image_url){
      const image=document.createElement("img");
      image.src=card.reference_image_url;
      image.alt="";
      thumb.appendChild(image);
    }
    const identity=document.createElement("span");
    identity.className="ui4-history-identity";
    const name=document.createElement("strong");
    name.textContent=card.card_name||card.printed_name||"Unknown card";
    const meta=document.createElement("span");
    meta.textContent=[card.set_name,card.collector_number].filter(Boolean).join(" • ")||"Set details unavailable";
    identity.append(name,meta);
    const result=document.createElement("span");
    result.className="ui4-history-result";
    const confidence=document.createElement("b");
    confidence.textContent=`${recentScanConfidence(card.confidence)}%`;
    const stamp=document.createElement("time");
    stamp.textContent=card.timestamp?new Date(Number(card.timestamp)*1000).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"}):"—";
    result.append(confidence,stamp);
    row.append(thumb,identity,result);
    list.appendChild(row);
  });
  view.appendChild(list);
}

async function loadUI4RecentScans(){
  const view=document.querySelector(".ui4-recent-scans-view");
  if(view) view.setAttribute("aria-busy","true");
  try{
    const payload=await api("/api/recent-pulls?limit=20");
    renderUI4RecentScans(Array.isArray(payload.cards)?payload.cards:[]);
  }catch{
    renderUI4RecentScans([]);
  }finally{
    if(view) view.setAttribute("aria-busy","false");
  }
}

function setUI4InspectorView(name,loadHistory=true){
  ui4InspectorView=name==="recent"?"recent":"current";
  document.querySelectorAll("[data-inspector-view]").forEach(button=>{
    const selected=button.dataset.inspectorView===ui4InspectorView;
    button.classList.toggle("active",selected);
    button.setAttribute("aria-selected",selected?"true":"false");
    button.tabIndex=selected?0:-1;
  });
  const current=document.querySelector(".ui4-current-card-view");
  const recent=document.querySelector(".ui4-recent-scans-view");
  if(current) current.hidden=ui4InspectorView!=="current";
  if(recent) recent.hidden=ui4InspectorView!=="recent";
  if(ui4InspectorView==="recent"&&loadHistory) loadUI4RecentScans();
}

function initializeStudioXUI4(){
  const camera=document.querySelector(".camera-workspace");
  const inspector=document.querySelector(".inspector");
  const inspectorMount=document.querySelector(".ui4-inspector-column");
  const pipeline=document.querySelector(".pipeline-rail");
  const dock=document.querySelector(".dock");
  const toolbar=document.querySelector(".toolbar");
  const appbar=document.querySelector(".appbar");
  if(!camera||!inspector||!inspectorMount||!pipeline||!dock||!toolbar||!appbar) return;

  inspectorMount.appendChild(inspector);
  camera.appendChild(pipeline);
  dock.classList.add("ui4-diagnostics-drawer");
  dock.setAttribute("aria-hidden","true");
  camera.appendChild(dock);

  const rail=document.querySelector(".ui4-navigation-rail");
  if(rail && !rail.querySelector('[data-ui4-action="rail"]')){
    const toggle=document.createElement("button");
    toggle.className="ui4-rail-toggle";
    toggle.dataset.ui4Action="rail";
    toggle.type="button";
    toggle.setAttribute("aria-label","Toggle compact navigation");
    toggle.textContent="Menu";
    toggle.addEventListener("click",()=>document.body.classList.toggle("ui4-rail-compact"));
    rail.prepend(toggle);
  }

  const recovery=toolbar.querySelector('[onclick="reconnectCamera()"]');
  if(recovery) recovery.textContent="Reconnect";
  const manual=toolbar.querySelector('[onclick="captureCamera()"]');
  if(manual) manual.textContent="Capture";

  const healthButton=document.createElement("button");
  healthButton.className="ui4-command-button";
  healthButton.dataset.ui4Action="health";
  healthButton.type="button";
  healthButton.textContent="Status";
  healthButton.setAttribute("aria-expanded","false");
  healthButton.addEventListener("click",()=>setUI4HealthOpen(!ui4HealthOpen));

  const diagnosticsButton=document.createElement("button");
  diagnosticsButton.className="ui4-command-button";
  diagnosticsButton.dataset.ui4Action="diagnostics";
  diagnosticsButton.type="button";
  diagnosticsButton.textContent="Diagnostics";
  diagnosticsButton.setAttribute("aria-expanded","false");
  diagnosticsButton.addEventListener("click",()=>setUI4DiagnosticsOpen(!ui4DiagnosticsOpen));
  toolbar.append(diagnosticsButton,healthButton);

  const healthPopover=document.createElement("div");
  healthPopover.className="ui4-health-popover";
  healthPopover.setAttribute("aria-hidden","true");
  const lowFrequency=[
    toolbar.querySelector('[onclick="loadCameraList()"]'),
    toolbar.querySelector('[onclick="reconnectCamera()"]'),
    toolbar.querySelector('[onclick="startSelectedCamera()"]'),
    toolbar.querySelector('[onclick="stopCamera()"]'),
    toolbar.querySelector('[onclick="openCameraPopout()"]'),
    $("resolutionBadge"),
    document.querySelector(".ui4-app-health"),
    document.querySelector(".system-status-strip"),
  ].filter(Boolean);
  lowFrequency.forEach(node=>healthPopover.appendChild(node));
  document.querySelector(".ui4-command-bar")?.appendChild(healthPopover);

  const primaryTabs=inspector.querySelector(".ui4-inspector-primary-tabs");
  const currentView=document.createElement("div");
  currentView.className="ui4-current-card-view";
  const recentView=document.createElement("div");
  recentView.className="ui4-recent-scans-view";
  recentView.hidden=true;
  [...inspector.children].forEach(child=>{
    if(child!==primaryTabs&&!child.classList.contains("inspector-head")) currentView.appendChild(child);
  });
  inspector.append(currentView,recentView);
  primaryTabs?.querySelectorAll("[data-inspector-view]").forEach(button=>{
    button.addEventListener("click",()=>setUI4InspectorView(button.dataset.inspectorView));
  });

  const tabs=document.createElement("div");
  tabs.className="ui4-inspector-tabs";
  tabs.setAttribute("role","tablist");
  const panels=document.createElement("div");
  panels.className="ui4-inspector-panels";
  const tabDefinitions=[
    ["details","Details",null],
    ["market","Market",document.querySelector(".market-grid")],
    ["copilot","Copilot",document.querySelector(".copilot-card")],
    ["signals","Signals",document.querySelector(".signal-list")],
    ["session","Session",document.querySelector(".session-strip")],
  ];
  tabDefinitions.forEach(([key,label,content])=>{
    const button=document.createElement("button");
    button.type="button";
    button.dataset.inspectorTab=key;
    button.setAttribute("role","tab");
    button.textContent=label;
    button.addEventListener("click",()=>setUI4InspectorTab(key));
    tabs.appendChild(button);
    const panel=document.createElement("section");
    panel.dataset.inspectorPanel=key;
    panel.setAttribute("role","tabpanel");
    if(content) panel.appendChild(content);
    else panel.innerHTML='<p class="ui4-panel-note">Candidate identity and recognition status remain visible above.</p>';
    panels.appendChild(panel);
  });
  currentView.append(tabs,panels);

  const actions=document.querySelector(".inspector-actions");
  const reaction=actions?[...actions.querySelectorAll("button")].find(button=>button.textContent.trim()==="Reaction"):null;
  if(reaction){
    reaction.textContent="Next / Clear";
    reaction.addEventListener("click",()=>resetRecognitionPresentation("operator_clear"));
  }
  setUI4InspectorTab("details");
  setUI4InspectorView("current",false);
  setUI4DiagnosticsOpen(false);
  setUI4HealthOpen(false);
  switchWorkspace("live");
}


document.addEventListener("DOMContentLoaded",()=>{
  initializeStudioXUI4();
  setTimeout(()=>verifyAndConnectMainViewer(),120);
  const bridgeFeed=$("cameraFeed");
  if(bridgeFeed){
    bridgeFeed.addEventListener("load",()=>{
      markViewerLive();
    });
    bridgeFeed.addEventListener("error",()=>{
      markViewerOffline();
      setViewerBridgeState("connecting","RECOVERING VIEWER");
      clearTimeout(viewerBridgeTimer);
      viewerBridgeTimer=setTimeout(()=>connectMainViewer(true),700);
    });
  }

  document.querySelectorAll(".nav-button").forEach(button=>{
    button.addEventListener("click",()=>switchWorkspace(button.dataset.target));
  });
  document.querySelectorAll(".dock-tab").forEach(button=>{
    button.addEventListener("click",()=>switchDock(button.dataset.dock));
  });

  const feed = $("cameraFeed");
  if(feed){
    feed.addEventListener("load",()=>{
      clearTimeout(cameraStreamRetryTimer);
      cameraStreamFailures=0;
      cameraStreamStarted=true;
      cameraAutostartComplete=true;
      alignScanZone(window.__rareiqVisionTelemetry||{});
      const placeholder=$("cameraPlaceholder");
      const recovery=$("cameraRecovery");
      if(placeholder) placeholder.classList.add("hidden");
      if(recovery) recovery.classList.remove("visible");
    });

    feed.addEventListener("error",()=>{
      clearTimeout(cameraStreamRetryTimer);
      cameraStreamStarted=false;
      cameraStreamFailures+=1;
      const placeholder=$("cameraPlaceholder");
      const recovery=$("cameraRecovery");
      if(placeholder) placeholder.classList.remove("hidden");

      if(cameraStreamFailures<=8){
        if(recovery){
          recovery.classList.add("visible");
          $("cameraRecoveryTitle").textContent="Recovering live previewâ€¦";
          $("cameraRecoveryDetail").textContent=`Retry ${cameraStreamFailures} of 8`;
        }
        cameraStreamRetryTimer=setTimeout(()=>startCameraStream(true),650);
      }else if(recovery){
        cameraAutostartComplete=false;
        recovery.classList.add("visible");
        $("cameraRecoveryTitle").textContent="Live preview unavailable";
        $("cameraRecoveryDetail").textContent="RareIQ will keep trying automatically.";
        scheduleCameraDiscovery();
      }
    });
  }

  const savedFit=localStorage.getItem("rareiq.cameraFitMode")||"adaptive";
  applyCameraFit(savedFit);
  applyCardZoom(localStorage.getItem("rareiq.cardZoom")==="on");
  updateResolutionBadge();
  window.addEventListener("resize",()=>{
    alignScanZone(window.__rareiqVisionTelemetry||{});
  });
  applyAutoCaptureState(true);
  setStateChip("databaseStateChip","on","READY");
  setStateChip("broadcastStateChip","","OFF");
  setRecognitionState("idle","Waiting for a card.");
  addActivity("RareIQ Ready","Camera and recognition controls loaded.");
  updateSessionStats();
  setInterval(updateSessionStats,1000);

  startBackgroundInitialization();


  setInterval(loadRecognition,600);
});
