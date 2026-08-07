
const $ = id => document.getElementById(id);
let selectedCamera = null;
let cameraStreamStarted = false;
let previousCardId = null;
let autoCaptureEnabled = true;
let captureBannerTimer = null;
let newestRecognitionGeneration = -1;
let newestRecognitionRevision = -1;
let currentServerSessionId = null;
let studioXExactMatchMomentKey = null;
let studioXExactMatchMomentTimer = null;
let activityItems = [];
let cameraFitMode = "adaptive";
let cardZoomEnabled = false;
const STUDIOX_PREFERENCES_KEY="rareiq.studiox.workspacePreferences.v1";
const STUDIOX_SECONDARY_BAY_KEY="rareiq.studiox.secondaryBayPreferences.v1";
const CAMERA_WORKSPACE_KEY="rareiq.studiox.cameraWorkspace.v1";
const CAMERA_WORKSPACE_LAYOUTS=["single","dual-side","triple","quad"];
const CAMERA_RECOVER_ENDPOINT="/api/camera/recover";
let studioXPreferences={
  version:1,
  layoutPreset:"intelligence",
  viewerMode:"auto",
  previewZoom:1,
};
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
let cameraConnectionAvailable = null;
let cameraConnectionFailure = null;
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
let cardPlaceholderResetTimer = null;
let secondaryFocusGeometry = null;
let lastValidCardFocusGeometry = null;
let lastValidCardFocusAt = 0;
let lastCardFocusGeometryReason = "unavailable";
const CARD_FOCUS_LAST_VALID_MS = 1800;
let secondaryBayPreferences={
  version:1,
  mode:"camera-2",
  visible:true,
  size:"standard",
  activeSource:null,
  stagingSource:null,
  manualPinned:false,
};
let cameraWorkspacePreferences={
  version:1,
  layout:"single",
  activeSlot:1,
  sources:{"1":null,"2":null,"3":null,"4":null},
  sides:{"1":"unassigned","2":"unassigned","3":"unassigned","4":"unassigned"},
};
let cameraWorkspaceSlotStates={};





function notify(title,detail="",type="info"){
  const stack=$("notificationStack");
  if(!stack) return;

  const node=document.createElement("div");
  node.className=`riq-notification ${type}`;
  node.innerHTML=`
    <div class="notification-icon">${type==="success"?"âœ“":type==="error"?"!":"â--†"}</div>
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
  const accuracy=sessionAttempts?`${Math.round(sessionMatches/sessionAttempts*100)}%`:"--";

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
  const stage=workspace?.querySelector(".camera-stage-inner");
  const feed=$("cameraFeed");
  const zone=$("scanZone");
  if(!workspace||!stage||!feed||!zone) return;

  const actual=vision.actual_resolution||[];
  const sourceWidth=Number(feed.naturalWidth||actual[0]||0);
  const sourceHeight=Number(feed.naturalHeight||actual[1]||0);
  const workspaceWidth=stage.clientWidth;
  const workspaceHeight=stage.clientHeight;
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
  const offsetX=stage.offsetLeft+(workspaceWidth-renderedWidth)/2;
  const offsetY=stage.offsetTop+(workspaceHeight-renderedHeight)/2;
  workspace.style.setProperty("--camera-render-left",`${offsetX}px`);
  workspace.style.setProperty("--camera-render-top",`${offsetY}px`);

  zone.style.left=`${offsetX+renderedWidth*Number(zoneValues.left)}px`;
  zone.style.top=`${offsetY+renderedHeight*Number(zoneValues.top)}px`;
  zone.style.width=`${renderedWidth*(Number(zoneValues.right)-Number(zoneValues.left))}px`;
  zone.style.height=`${renderedHeight*(Number(zoneValues.bottom)-Number(zoneValues.top))}px`;
  zone.style.right="auto";
  zone.style.bottom="auto";
  applyStudioXViewerPresentation(
    window.__rareiqCardContext||null,
    vision
  );
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

function applyRecognitionPresentation(presentation){
  const panel=$("recognitionStatePanel");
  const label=$("recognitionStateLabel");
  const placeholder=$("cardPlaceholder");
  const key=presentation?.key||"ready";
  const title=presentation?.title||"READY";
  const detail=presentation?.detail||"";
  const confidence=normalize(presentation?.confidence||0);
  const legacyState=
    key==="exact-match" ? "matched" :
    key==="error" ? "error" :
    key==="ready" ? "idle" :
    "searching";
  clearTimeout(cardPlaceholderResetTimer);
  if(placeholder){
    placeholder.classList.remove(
      "state-waiting","state-searching","state-matched","state-error"
    );
    placeholder.classList.add(
      key==="exact-match" ? "state-matched" :
      key==="error" ? "state-error" :
      key==="ready" ? "state-waiting" :
      "state-searching"
    );
    placeholder.dataset.recognitionState=key;
  }
  if($("cardPlaceholderTitle")){
    $("cardPlaceholderTitle").textContent=presentation?.placeholderTitle||title;
  }
  if($("cardPlaceholderDetail")){
    $("cardPlaceholderDetail").textContent=presentation?.placeholderDetail||detail;
  }
  if($("aiState")) $("aiState").textContent=title;
  if($("aiDetail")) $("aiDetail").textContent=detail;
  if($("confidence")) $("confidence").textContent=`${Math.round(confidence*100)}%`;
  if($("cardStatus")) $("cardStatus").textContent=title;
  if($("cameraFeedStateLabel")) $("cameraFeedStateLabel").textContent=title;
  if($("unifiedScanStatus")){
    $("unifiedScanStatus").dataset.state=key;
    $("unifiedScanStatus").dataset.presentation=key;
  }
  const progressIndex={
    ready:0,
    detecting:1,
    scanning:1,
    "candidate-found":2,
    verifying:2,
    "review-needed":2,
    "exact-match":3,
    error:0,
  }[key]??0;
  document.querySelectorAll("[data-recognition-stage]").forEach((stage,index)=>{
    stage.classList.toggle("complete",index<progressIndex);
    stage.classList.toggle("current",index===progressIndex);
    if(index===progressIndex){
      stage.setAttribute("aria-current","step");
    }else{
      stage.removeAttribute("aria-current");
    }
  });
  const detailNode=$("recognitionStateDetail");
  if(panel){
    panel.classList.remove("idle","searching","matched","captured","error");
    panel.classList.add(legacyState);
  }
  const cameraWorkspace=document.querySelector(".camera-workspace");
  if(cameraWorkspace){
    cameraWorkspace.classList.remove(
      "state-idle","state-searching","state-matched","state-captured","state-error"
    );
    cameraWorkspace.classList.add(`state-${legacyState}`);
    cameraWorkspace.dataset.recognitionState=key;
  }
  if(label) label.textContent=title;
  if(detailNode) detailNode.textContent=detail;
  const aiChipState =
    legacyState==="searching" ? "working" :
    legacyState==="matched" ? "on" :
    legacyState==="error" ? "error" : "";
  setStateChip("aiStateChip",aiChipState,title);
  updateAiPulse(legacyState);
  setCoreState(key);
}

function setRecognitionState(state,detail=""){
  const legacyPresentations={
    idle:{key:"ready",title:"READY",placeholderTitle:"Ready for Card"},
    searching:{key:"scanning",title:"SCANNING",placeholderTitle:"Scanning Card"},
    captured:{key:"verifying",title:"VERIFYING",placeholderTitle:"Verifying Card"},
    matched:{key:"exact-match",title:"EXACT MATCH",placeholderTitle:"Exact Match"},
    error:{key:"error",title:"ERROR",placeholderTitle:"Recognition Unavailable"},
  };
  applyRecognitionPresentation({
    ...(legacyPresentations[state]||legacyPresentations.idle),
    detail,
    confidence:0,
  });
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

    const camera=readSelectedCamera();
    if(!camera) throw new Error("Select a camera source.");

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
  const camera=readSelectedCamera();
  if(!camera){
    setCameraStatus("SELECT A CAMERA","var(--gold)");
    updateActiveCameraName(null,"select");
    showOperatorToast("Select a camera before restarting it.","error");
    return;
  }
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
  await ensureCameraStarted(true);
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
        "Camera starting...",
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
      "Starting camera...",
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
      cameraConnectionAvailable=true;
      cameraConnectionFailure=null;
      setCameraActionAvailability(true);
      updateActiveCameraName(camera,"active");
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
    setCameraDisconnectedPresentation(camera,error?.message||`Could not open ${camera.name||"selected camera"}`);
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
      const camera=readSelectedCamera();
      if(camera) await ensureCameraStarted();
      else return;
    }

    if(!cameraAutostartComplete){
      scheduleCameraDiscovery();
    }
  },1600);
}

async function loadCameraList(options={}){
  const {retries=5,delay=650,silent=false}=options;
  const force=options.force??!silent;
  const select=$("cameraSelect");
  if(!silent) select.innerHTML=`<option value="">Scanning cameras...</option>`;

  for(let attempt=0;attempt<=retries;attempt+=1){
    try{
      const result=await api(`/api/cameras?force=${force?"true":"false"}`);
      const cameras=sortCameraDevices(result.cameras||[]);
      if(cameras.length){
        const saved=localStorage.getItem("rareiq.selectedCamera");
        const savedCamera=decodeCameraValue(saved);
        const savedVirtual=isVirtualCamera(savedCamera);
        const prompt=savedVirtual
          ?"Saved virtual camera requires confirmation"
          :saved
          ?"Saved camera unavailable -- select a camera"
          :"Select a camera";
        select.replaceChildren();
        const promptOption=document.createElement("option");
        promptOption.value="";
        promptOption.textContent=prompt;
        select.appendChild(promptOption);
        appendCameraGroup(select,"Physical Cameras",cameras.filter(camera=>!isVirtualCamera(camera)));
        appendCameraGroup(select,"Virtual Cameras",cameras.filter(isVirtualCamera));
        const savedMatch=saved&&[...select.options].find(option=>{
          if(option.value===saved) return true;
          const candidate=decodeCameraValue(option.value);
          return candidate&&savedCamera&&
            Number(candidate.index)===Number(savedCamera.index)&&
            Number(candidate.backend)===Number(savedCamera.backend);
        });
        const savedAvailable=Boolean(savedMatch);
        if(savedAvailable&&!savedVirtual){
          select.value=savedMatch.value;
          localStorage.setItem("rareiq.selectedCamera",savedMatch.value);
          readSelectedCamera();
          updateActiveCameraName(selectedCamera,"selected");
        }else{
          select.value="";
          selectedCamera=null;
          updateActiveCameraName(savedVirtual?savedCamera:null,savedVirtual?"virtual":"select");
        }
        syncSecondarySourceOptions(cameras);
        syncCameraWorkspaceSourceOptions();
        renderCameraWorkspace();
        await refreshCameraSlotState();
        return cameras;
      }
    }catch{}

    if(attempt<retries){
      select.innerHTML=`<option value="">Camera scan retry ${attempt+1}/${retries}...</option>`;
      await new Promise(resolve=>setTimeout(resolve,delay));
    }
  }

  select.innerHTML=`<option value="">No cameras detected</option>`;
  selectedCamera=null;
  updateActiveCameraName(null,"none");
  syncSecondarySourceOptions([]);
  syncCameraWorkspaceSourceOptions();
  renderCameraWorkspace();
  return [];
}

const VIRTUAL_CAMERA_TERMS=[
  "virtual","obs","streamlabs","manycam","snap camera","ndi","intcast",
  "bytecast","xsplit","iriun","epoccam","droidcam"
];

function isVirtualCamera(camera){
  const name=String(camera?.name||"").trim().toLowerCase();
  return Boolean(name&&VIRTUAL_CAMERA_TERMS.some(term=>name.includes(term)));
}

function decodeCameraValue(value){
  if(!value) return null;
  try{
    return JSON.parse(decodeURIComponent(value));
  }catch{
    return null;
  }
}

function cameraOptionValue(camera,index=0){
  return encodeURIComponent(JSON.stringify({
    source_id:camera?.source_id||null,
    index:Number(camera?.index??index),
    backend:Number(camera?.backend??700),
    name:camera?.name||`Camera ${index+1}`
  }));
}

function sourceIdFromCameraValue(value){
  return decodeCameraValue(value)?.source_id||null;
}

function sortCameraDevices(cameras=[]){
  return [...cameras].sort((left,right)=>{
    const virtualOrder=Number(isVirtualCamera(left))-Number(isVirtualCamera(right));
    if(virtualOrder) return virtualOrder;
    const instaOrder=Number(!/insta360/i.test(left?.name||""))-Number(!/insta360/i.test(right?.name||""));
    if(instaOrder) return instaOrder;
    const nameOrder=String(left?.name||"").localeCompare(String(right?.name||""));
    if(nameOrder) return nameOrder;
    return Number(left?.backend||0)-Number(right?.backend||0);
  });
}

function appendCameraGroup(select,label,cameras){
  if(!cameras.length) return;
  const group=document.createElement("optgroup");
  group.label=label;
  cameras.forEach((camera,index)=>{
    const option=document.createElement("option");
    option.value=cameraOptionValue(camera,index);
    option.textContent=`${camera.name||`Camera ${index+1}`}${camera.backend_name?`  |  ${camera.backend_name}`:""}`;
    option.dataset.cameraKind=isVirtualCamera(camera)?"virtual":"physical";
    group.appendChild(option);
  });
  select.appendChild(group);
}

async function runCameraSourceAction(select){
  const action=select?.value||"";
  if(select) select.value="";
  if(action==="refresh") await loadCameraList({force:true});
  else if(action==="reconnect") await reconnectCamera();
  else if(action==="restart") await restartFeed();
}

function arrangeCameraToolbar(){
  const toolbar=document.querySelector(".toolbar");
  if(!toolbar) return;
  const menu=toolbar.querySelector(".premium-more-menu");
  const popover=toolbar.querySelector(".premium-more-popover");
  const actions=toolbar.querySelector(".premium-actions-row");
  const compact=window.matchMedia("(max-width: 1180px)").matches;
  const secondary=[
    document.querySelector('[data-ui4-action="diagnostics"]'),
    document.querySelector('[data-ui4-action="health"]'),
  ].filter(Boolean);
  if(compact&&popover){
    secondary.forEach(node=>popover.appendChild(node));
  }else if(actions){
    secondary.forEach(node=>actions.appendChild(node));
  }
  if(menu?.open&&compact){
    menu.open=false;
  }
}

function updateActiveCameraName(camera,state="active"){
  const output=$("activeCameraName");
  if(!output) return;
  if(!camera){
    output.textContent=state==="none"?"No cameras detected":"Select a camera";
    output.dataset.state=state;
    return;
  }
  const label=camera.name||`Camera ${Number(camera.index)+1}`;
  const select=$("cameraSelect");
  const matchingOption=[...(select?.options||[])].find(option=>{
    const candidate=decodeCameraValue(option.value);
    return candidate&&(
      (Number(candidate.index)===Number(camera.index)&&Number(candidate.backend)===Number(camera.backend))||
      String(candidate.name||"").trim()===String(camera.name||"").trim()
    );
  });
  if(select&&matchingOption) select.value=matchingOption.value;
  output.textContent=
    state==="virtual"?`${label} -- confirmation required`:
    state==="disconnected"?`${label} -- disconnected`:
    `Active: ${label}`;
  output.dataset.state=state;
  updateViewerInspectionHeader();
}

function updateViewerInspectionHeader(
  context=window.__rareiqCardContext||null
){
  const source=$("viewerInspectionSource");
  const mode=$("viewerInspectionMode");
  const cardState=$("viewerInspectionCardState");
  const recognition=$("viewerInspectionRecognitionMode");
  const activeLabel=$("activeCameraName")?.textContent?.trim()||"Select a camera";
  if(source){
    source.textContent=activeLabel.replace(/^Active:\s*/i,"");
  }
  if(mode){
    mode.textContent=$("viewerModeStatus")?.textContent?.trim()||"Auto · full frame";
  }
  if(cardState){
    cardState.textContent=context?.presentation?.title||"READY";
  }
  if(recognition){
    recognition.textContent=
      context?.verified===true
        ?"Verified identity"
        :context?.card
        ?"Candidate review"
        :"Live recognition";
  }
}

function setCameraActionAvailability(connected){
  document.body.classList.toggle("camera-disconnected",!connected);
  const capture=document.querySelector('[onclick="captureCamera()"]');
  const auto=$("autoCaptureToggle");
  if(capture) capture.disabled=!connected;
  if(auto) auto.disabled=!connected;
}

function setCameraDisconnectedPresentation(camera,error=""){
  cameraConnectionAvailable=false;
  cameraConnectionFailure={camera,error:String(error||"")};
  markViewerOffline();
  setCameraActionAvailability(false);
  const name=camera?.name||"Selected camera";
  const failure=String(error||"").trim();
  const failedSource=failure.toLowerCase().includes(name.toLowerCase())
    ?failure
    :`Could not open ${name}`;
  const detail=`${failedSource.replace(/[.\s]+$/g,"")}. Select a physical camera or refresh devices`;
  setCameraStatus("CAMERA DISCONNECTED","var(--red)");
  setStateChip("cameraStateChip","error","DISCONNECTED");
  updateActiveCameraName(camera,"disconnected");
  applyRecognitionPresentation({
    key:"error",
    state:"error",
    title:"DISCONNECTED",
    detail,
    placeholderTitle:"Camera Disconnected",
    placeholderDetail:"Select a physical camera or refresh devices",
    confidence:0,
  });
  const recovery=$("cameraRecovery");
  if(recovery){
    recovery.classList.remove("suppressed","success");
    recovery.classList.add("visible","error");
  }
  if($("cameraRecoveryTitle")) $("cameraRecoveryTitle").textContent=`Could not open ${name}`;
  if($("cameraRecoveryDetail")) $("cameraRecoveryDetail").textContent="Select a physical camera or refresh devices";
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
  resetRecognitionPresentation("active_source_changed");
  readSelectedCamera();
  secondaryBayPreferences.activeSource=$("cameraSelect")?.value||null;
  cameraWorkspacePreferences.sources["1"]=$("cameraSelect")?.value||null;
  [2,3,4].forEach(slot=>{
    if(cameraWorkspacePreferences.sources[String(slot)]===cameraWorkspacePreferences.sources["1"]){
      cameraWorkspacePreferences.sources[String(slot)]=null;
      if(slot===2) secondaryBayPreferences.stagingSource=null;
    }
  });
  normalizeSecondarySourcePair();
  saveSecondaryBayPreferences();
  saveCameraWorkspacePreferences();
  renderSecondaryWorkspaceBay();
  renderCameraWorkspace();
  cameraAutostartComplete=false;
  if(!selectedCamera){
    updateActiveCameraName(null,"select");
    return;
  }
  updateActiveCameraName(selectedCamera,"selected");
  const started=await ensureCameraStarted(true);
  if(started) updateActiveCameraName(selectedCamera,"active");
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
  const camera=readSelectedCamera();
  if(!camera){
    setCameraDisconnectedPresentation(
      null,
      "Select a physical camera or refresh devices"
    );
    return;
  }
  cameraAutostartComplete=false;
  cameraStreamStarted=false;
  cameraStreamFailures=0;

  setCameraRecovery(
    `Reconnecting ${camera.name||"camera"}...`,
    "RareIQ is reopening the exact selected source."
  );

  try{
    const connected=await ensureCameraStarted(true);
    if(!connected) throw new Error(`Could not open ${camera.name||"selected camera"}`);
    updateActiveCameraName(camera,"active");
  }catch(error){
    setCameraDisconnectedPresentation(camera,error?.message);
  }
}

async function captureCamera(){
  setRecognitionState("searching","Saving current corrected card crop...");
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
    $("cameraRecoveryTitle").textContent="Connecting camera...";
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
          $("cameraRecoveryTitle").textContent="Restoring live preview...";
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
      "Discovering cameras...",
      "RareIQ is scanning Windows video devices."
    );

    const cameras=await loadCameraList({
      retries:10,
      delay:700
    });

    if(!cameras.length){
      setCameraStatus("CAMERA NOT FOUND","var(--gold)");
      setStateChip("cameraStateChip","warning","DISCOVERING");
      setCameraRecovery(
        "Waiting for camera...",
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
    cameraConnectionAvailable=online;
    cameraConnectionFailure=online?null:{
      camera:manager.selected_camera||selectedCamera,
      error:manager.last_error||manager.message||"Camera is disconnected",
    };
    updateActiveCameraName(
      manager.selected_camera||selectedCamera,
      online?"active":"disconnected"
    );
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

    if(online){
      setCameraActionAvailability(true);
    }else{
      setCameraDisconnectedPresentation(
        cameraConnectionFailure.camera,
        cameraConnectionFailure.error
      );
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
  waiting:" | ",active:"▶",complete:"✓",warning:"!",failed:"×",skipped:"–"
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
  if(["detecting","scanning","candidate-found","verifying","review-needed"].includes(normalized)){
    orb.classList.add("scanning");
    label.textContent=normalized.replaceAll("-"," ").toUpperCase();
  }else if(["matched","verified","exact-match"].includes(normalized)){
    orb.classList.add("matched");
    label.textContent="EXACT MATCH";
  }else if(normalized==="complete"){
    orb.classList.add("complete");
    label.textContent="COMPLETE";
  }else if(normalized==="error"){
    label.textContent="ERROR";
  }else{
    label.textContent="READY";
  }
}

function resetRecognitionPresentation(reason="reset"){
  clearCardFocusGeometry();
  resetUI4PresentationSurfaces();
  previousCardId=null;
  const empty=$("inspectorEmpty");
  const main=$("inspectorMain");
  if(empty) empty.style.display="none";
  if(main) main.style.display="grid";
  if($("cardArt")) $("cardArt").innerHTML="";
  if($("cardName")) $("cardName").textContent="Ready to Scan";
  if($("cardMeta")) $("cardMeta").textContent="";
  if($("cardStatus")) $("cardStatus").textContent="READY";
  if($("confidence")) $("confidence").textContent="0%";
  updateConfidenceRing(0);
  setSignal("vision",0);
  setSignal("ocr",0);
  setSignal("collector",0);
  setSignal("fusion",0);
  renderPipeline([],false);
  resetExtendedCardData();
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
  updateSharedCardContext(
    deriveSharedCardContext(
      deriveRecognitionPresentation({phase:"IDLE"},null,[]),
      null,
      {phase:"IDLE"},
      []
    )
  );
}

function normalizeStudioXPreferences(value){
  const layouts=["intelligence","balanced","monitor"];
  const viewerModes=["auto","full-frame","card-focus"];
  const zoom=Number(value?.previewZoom);
  return {
    version:1,
    layoutPreset:layouts.includes(value?.layoutPreset)
      ? value.layoutPreset
      : "intelligence",
    viewerMode:viewerModes.includes(value?.viewerMode)
      ? value.viewerMode
      : "auto",
    previewZoom:Number.isFinite(zoom)
      ? Math.max(.8,Math.min(2.5,zoom))
      : 1,
  };
}

function normalizeCameraWorkspacePreferences(value){
  const source=value?.sources&&typeof value.sources==="object"?value.sources:{};
  const sides=value?.sides&&typeof value.sides==="object"?value.sides:{};
  const normalizeSource=slot=>typeof source[String(slot)]==="string"&&source[String(slot)]?source[String(slot)]:null;
  const normalizeSide=slot=>["unassigned","player-1","player-2"].includes(sides[String(slot)])?sides[String(slot)]:"unassigned";
  const savedLayout=value?.layout==="dual-stack"?"dual-side":value?.layout;
  return {
    version:1,
    layout:CAMERA_WORKSPACE_LAYOUTS.includes(savedLayout)?savedLayout:"single",
    activeSlot:[1,2,3,4].includes(Number(value?.activeSlot))?Number(value.activeSlot):1,
    sources:{"1":normalizeSource(1),"2":normalizeSource(2),"3":normalizeSource(3),"4":normalizeSource(4)},
    sides:{"1":normalizeSide(1),"2":normalizeSide(2),"3":normalizeSide(3),"4":normalizeSide(4)},
  };
}

function loadCameraWorkspacePreferences(){
  try{
    return normalizeCameraWorkspacePreferences(JSON.parse(localStorage.getItem(CAMERA_WORKSPACE_KEY)||"null"));
  }catch{
    return normalizeCameraWorkspacePreferences(null);
  }
}

function saveCameraWorkspacePreferences(){
  try{localStorage.setItem(CAMERA_WORKSPACE_KEY,JSON.stringify(cameraWorkspacePreferences));}catch{}
}

async function refreshCameraSlotState(){
  try{
    const result=await api("/api/camera-slots");
    (result.slots||[]).forEach(slot=>{
      const id=String(slot.slot_id);
      cameraWorkspaceSlotStates[id]=slot;
      cameraWorkspacePreferences.sources[id]=slot.source
        ?cameraOptionValue(slot.source,slot.slot_id-1)
        :null;
      cameraWorkspacePreferences.sides[id]=slot.side||"unassigned";
      if(slot.role==="active"){
        cameraWorkspacePreferences.activeSlot=slot.slot_id;
        const active=$("cameraSelect");
        const value=cameraWorkspacePreferences.sources[id];
        if(active&&value&&[...active.options].some(option=>option.value===value)) active.value=value;
      }
      if(slot.slot_id===2) secondaryBayPreferences.stagingSource=cameraWorkspacePreferences.sources[id];
    });
    saveSecondaryBayPreferences();
    saveCameraWorkspacePreferences();
    renderCameraWorkspace();
    return result;
  }catch{
    return null;
  }
}

function cameraWorkspaceVisibleSlots(layout=cameraWorkspacePreferences.layout){
  return layout==="single"?[1]:layout==="dual-side"?[1,2]:layout==="triple"?[1,2,3]:[1,2,3,4];
}

function syncCameraWorkspaceSourceOptions(){
  const active=$("cameraSelect");
  if(!active) return;
  const selectForSlot=slot=>slot===1?$("cameraSlot1Source"):slot===2?$("stagingSourceSelect"):$(`cameraSlot${slot}Source`);
  [1,2,3,4].forEach(slot=>{
    const select=selectForSlot(slot);
    if(!select) return;
    const current=slot===1?active.value:cameraWorkspacePreferences.sources[String(slot)];
    select.replaceChildren();
    const prompt=document.createElement("option");
    prompt.value="";
    prompt.textContent=slot===1?"Select a camera":"No camera selected";
    select.appendChild(prompt);
    [...active.children].forEach(child=>{
      const target=child.tagName==="OPTGROUP"?document.createElement("optgroup"):select;
      if(child.tagName==="OPTGROUP") target.label=child.label;
      const options=child.tagName==="OPTGROUP"?[...child.children]:[child];
      options.filter(option=>option.value).forEach(option=>{
        const clone=option.cloneNode(true);
        const owner=[1,2,3,4].find(other=>other!==slot&&cameraWorkspacePreferences.sources[String(other)]===clone.value);
        if(owner){
          clone.disabled=true;
          clone.textContent=`${clone.textContent} — Camera ${owner}`;
        }
        target.appendChild(clone);
      });
      if(child.tagName==="OPTGROUP"&&target.children.length) select.appendChild(target);
    });
    const available=[...select.options].some(option=>option.value===current);
    if(current&&!available){
      const missing=document.createElement("option");
      const decoded=decodeCameraValue(current);
      missing.value=current;
      missing.textContent=`${decoded?.name||"Saved camera"} — missing`;
      missing.disabled=true;
      select.appendChild(missing);
    }
    select.value=current||"";
  });
}

function renderCameraWorkspace(){
  const workspace=document.querySelector(".camera-workspace");
  if(!workspace) return;
  const layout=cameraWorkspacePreferences.layout;
  const visible=new Set(cameraWorkspaceVisibleSlots(layout));
  workspace.dataset.cameraLayout=layout;
  workspace.dataset.activeSlot=String(cameraWorkspacePreferences.activeSlot);
  workspace.classList.toggle("has-secondary-bay",visible.has(2));
  document.querySelectorAll("[data-camera-layout-option]").forEach(button=>{
    const selected=button.dataset.cameraLayoutOption===layout;
    button.classList.toggle("is-selected",selected);
    button.setAttribute("aria-pressed",String(selected));
  });
  if($("cameraSlot1Side")) $("cameraSlot1Side").value=cameraWorkspacePreferences.sides["1"];
  if($("cameraSlot1Connection")) $("cameraSlot1Connection").textContent=cameraConnectionAvailable===true?"CONNECTED":cameraConnectionAvailable===false?"DISCONNECTED":"CONNECTING";
  if($("cameraSlot2Side")) $("cameraSlot2Side").value=cameraWorkspacePreferences.sides["2"];
  [3,4].forEach(slot=>{
    const tile=$(`cameraWorkspaceSlot${slot}`);
    const source=cameraWorkspacePreferences.sources[String(slot)];
    if(tile) tile.hidden=!visible.has(slot);
    if($(`cameraSlot${slot}Side`)) $(`cameraSlot${slot}Side`).value=cameraWorkspacePreferences.sides[String(slot)];
    if($(`promoteCameraSlot${slot}`)) $(`promoteCameraSlot${slot}`).disabled=!source;
    const connectionState=cameraWorkspaceSlotStates[String(slot)]?.connection_state;
    if($(`cameraSlot${slot}Connection`)) $(`cameraSlot${slot}Connection`).textContent=source
      ?String(connectionState||"connecting").toUpperCase()
      :"NOT CONNECTED";
    const preview=$(`cameraSlot${slot}Preview`);
    if(preview){
      if(source){
        preview.hidden=false;
        preview.onload=()=>{
          if($(`cameraSlot${slot}Connection`)) $(`cameraSlot${slot}Connection`).textContent="CONNECTED";
          const detail=tile?.querySelector(".camera-workspace-staging-surface span");
          if(detail) detail.hidden=true;
        };
        preview.onerror=()=>{
          preview.hidden=true;
          if($(`cameraSlot${slot}Connection`)) $(`cameraSlot${slot}Connection`).textContent="DISCONNECTED";
          const detail=tile?.querySelector(".camera-workspace-staging-surface span");
          if(detail){
            detail.hidden=false;
            detail.textContent="Camera disconnected";
          }
        };
        const url=`/api/camera-slots/${slot}/stream`;
        if(preview.getAttribute("src")!==url) preview.src=url;
      }else{
        preview.hidden=true;
        preview.removeAttribute("src");
      }
    }
    const detail=tile?.querySelector(".camera-workspace-staging-surface span");
    if(detail&&!source){
      detail.hidden=false;
      detail.innerHTML="No camera selected<br>Choose a source from Manage Cameras";
    }
  });
  const bay=$("secondaryWorkspaceBay");
  if(bay) bay.hidden=!visible.has(2);
  if($("cameraSlot2Connection")) $("cameraSlot2Connection").textContent=cameraWorkspacePreferences.sources["2"]
    ?String(cameraWorkspaceSlotStates["2"]?.connection_state||"connecting").toUpperCase()
    :"NOT CONNECTED";
  syncCameraWorkspaceSourceOptions();
}

function setCameraWorkspaceLayout(layout){
  cameraWorkspacePreferences=normalizeCameraWorkspacePreferences({...cameraWorkspacePreferences,layout});
  saveCameraWorkspacePreferences();
  renderCameraWorkspace();
  alignScanZone(window.__rareiqVisionTelemetry||{});
}

async function setCameraWorkspaceSource(slot,value){
  if(slot===1) return;
  const owner=[1,2,3,4].find(other=>other!==slot&&cameraWorkspacePreferences.sources[String(other)]===value);
  if(value&&owner){
    renderCameraWorkspace();
    return;
  }
  cameraWorkspacePreferences.sources[String(slot)]=value||null;
  if(slot===2){
    secondaryBayPreferences.stagingSource=value||null;
    saveSecondaryBayPreferences();
  }
  saveCameraWorkspacePreferences();
  try{
    await api(`/api/camera-slots/${slot}/source`,{
      method:"PUT",
      body:JSON.stringify({
        source_id:sourceIdFromCameraValue(value),
        side:cameraWorkspacePreferences.sides[String(slot)]
      })
    });
  }catch(error){
    cameraWorkspacePreferences.sources[String(slot)]=null;
    showToast(error.message||"Could not assign camera.");
  }
  renderCameraWorkspace();
}

async function setCameraWorkspaceSide(slot,value){
  cameraWorkspacePreferences.sides[String(slot)]=["player-1","player-2"].includes(value)?value:"unassigned";
  saveCameraWorkspacePreferences();
  const source=cameraWorkspacePreferences.sources[String(slot)];
  if(source){
    try{
      await api(`/api/camera-slots/${slot}/source`,{
        method:"PUT",
        body:JSON.stringify({
          source_id:sourceIdFromCameraValue(source),
          side:cameraWorkspacePreferences.sides[String(slot)]
        })
      });
    }catch(error){
      showToast(error.message||"Could not update camera side.");
    }
  }
}

async function promoteCameraWorkspaceSlot(slot){
  const active=$("cameraSelect");
  const source=cameraWorkspacePreferences.sources[String(slot)];
  if(!active||!source||source===active.value) return;
  try{
    await api(`/api/camera-slots/${slot}/activate`,{method:"POST"});
    cameraWorkspacePreferences.activeSlot=slot;
    active.value=source;
    saveCameraWorkspacePreferences();
    await refreshCameraSlotState();
    cameraStreamStarted=false;
    startCameraStream();
  }catch(error){
    showToast(error.message||"Could not activate camera.");
  }
}

async function setActiveCameraWorkspaceSource(value){
  const active=$("cameraSelect");
  if(!active||active.value===value) return;
  active.value=value||"";
  await selectCamera();
}

function normalizeSecondaryBayPreferences(value){
  const modes=["hidden","camera-2","card-focus","locked-capture","broadcast-preview","recent-captures"];
  const sizes=["compact","standard","large"];
  const firstRun=!value||typeof value!=="object";
  const requestedMode=modes.includes(value?.mode)?value.mode:"camera-2";
  const mode=(
    requestedMode==="hidden"||
    (requestedMode==="card-focus"&&value?.manualPinned!==true)
  )?"camera-2":requestedMode;
  return {
    version:1,
    mode,
    visible:true,
    size:sizes.includes(value?.size)?value.size:"standard",
    activeSource:typeof value?.activeSource==="string"&&value.activeSource?value.activeSource:null,
    stagingSource:typeof value?.stagingSource==="string"&&value.stagingSource?value.stagingSource:null,
    manualPinned:typeof value?.manualPinned==="boolean"
      ? value.manualPinned
      : !firstRun,
  };
}

function deriveAutoSecondaryBayPresentation(context=null){
  const manual={
    mode:secondaryBayPreferences.mode,
    visible:secondaryBayPreferences.visible,
    size:secondaryBayPreferences.size,
    automatic:false,
  };
  if(
    secondaryBayPreferences.mode==="hidden"||
    secondaryBayPreferences.manualPinned||
    secondaryBayPreferences.mode!=="card-focus"
  ) return manual;
  const key=context?.presentation?.key||"ready";
  const geometry=normalizedCardFocusGeometry(window.__rareiqVisionTelemetry||{});
  if(key==="verifying"&&geometry){
    return {mode:"card-focus",visible:true,size:"standard",automatic:true};
  }
  if(key==="exact-match"&&geometry){
    return {mode:"card-focus",visible:true,size:"standard",automatic:true};
  }
  if(["detecting","scanning","candidate-found"].includes(key)&&geometry){
    return {mode:"card-focus",visible:true,size:"compact",automatic:true};
  }
  return {mode:"card-focus",visible:false,size:"compact",automatic:true};
}

function loadSecondaryBayPreferences(){
  try{
    return normalizeSecondaryBayPreferences(
      JSON.parse(localStorage.getItem(STUDIOX_SECONDARY_BAY_KEY)||"null")
    );
  }catch{
    return normalizeSecondaryBayPreferences(null);
  }
}

function saveSecondaryBayPreferences(){
  try{
    localStorage.setItem(
      STUDIOX_SECONDARY_BAY_KEY,
      JSON.stringify(secondaryBayPreferences)
    );
  }catch{}
}

function normalizeSecondarySourcePair(){
  const active=$("cameraSelect")?.value||secondaryBayPreferences.activeSource||null;
  const available=new Set(
    [...($("cameraSelect")?.options||[])].map(option=>option.value).filter(Boolean)
  );
  secondaryBayPreferences.activeSource=available.has(active)?active:null;
  if(
    !available.has(secondaryBayPreferences.stagingSource)||
    secondaryBayPreferences.stagingSource===secondaryBayPreferences.activeSource
  ){
    secondaryBayPreferences.stagingSource=null;
  }
  if($("stagingSourceSelect")){
    $("stagingSourceSelect").value=secondaryBayPreferences.stagingSource||"";
  }
}

function syncSecondarySourceOptions(){
  const activeSelect=$("cameraSelect");
  const staging=$("stagingSourceSelect");
  if(!activeSelect||!staging) return;
  const current=secondaryBayPreferences.stagingSource;
  staging.innerHTML='<option value="">No staging camera</option>';
  [...activeSelect.options].filter(option=>option.value).forEach(option=>{
    const clone=document.createElement("option");
    clone.value=option.value;
    clone.textContent=option.textContent;
    staging.appendChild(clone);
  });
  secondaryBayPreferences.stagingSource=current;
  normalizeSecondarySourcePair();
  saveSecondaryBayPreferences();
  renderSecondaryWorkspaceBay();
}

function truthfulLockedCapture(context){
  const snapshot=context?.snapshot||{};
  const card=context?.card||{};
  const url=
    snapshot.locked_capture_url||
    snapshot.stable_capture_url||
    snapshot.capture_url||
    card.locked_capture_url||
    card.capture_url||
    null;
  return url?{
    url,
    capturedAt:snapshot.captured_at||card.captured_at||null,
  }:null;
}

function setSecondaryBayUnavailable(title,detail){
  const image=$("secondaryBayImage");
  const broadcast=$("secondaryBroadcastPreview");
  if(image){
    image.hidden=true;
    image.removeAttribute("src");
  }
  if(broadcast){
    broadcast.hidden=true;
    broadcast.removeAttribute("src");
  }
  if($("secondaryBayUnavailable")) $("secondaryBayUnavailable").hidden=false;
  if($("secondaryBayStateTitle")) $("secondaryBayStateTitle").textContent=title;
  if($("secondaryBayStateDetail")) $("secondaryBayStateDetail").textContent=detail;
}

function renderSecondaryWorkspaceBay(context=window.__rareiqCardContext||null){
  const bay=$("secondaryWorkspaceBay");
  const workspace=document.querySelector(".camera-workspace");
  if(!bay) return;
  normalizeSecondarySourcePair();
  const effective=deriveAutoSecondaryBayPresentation(context);
  const mode=effective.mode;
  const visible=effective.visible&&mode!=="hidden";
  bay.hidden=!visible;
  bay.dataset.bayMode=mode;
  bay.dataset.baySize=effective.size;
  bay.dataset.bayControl=effective.automatic?"automatic":"manual";
  workspace?.classList.toggle("has-secondary-bay",visible);
  const heights={
    compact:"var(--secondary-bay-compact)",
    standard:"var(--secondary-bay-standard)",
    large:"var(--secondary-bay-large)",
  };
  workspace?.style.setProperty("--secondary-bay-height",heights[effective.size]);
  if($("secondaryBayMode")) $("secondaryBayMode").value=mode;
  if($("secondaryBaySize")) $("secondaryBaySize").value=secondaryBayPreferences.size;
  const twoSources=Boolean(
    secondaryBayPreferences.activeSource&&
    secondaryBayPreferences.stagingSource&&
    secondaryBayPreferences.activeSource!==secondaryBayPreferences.stagingSource
  );
  ["swapSourcesButton","promoteStagingButton"].forEach(id=>{
    if($(id)) $(id).disabled=!twoSources;
  });
  if(!visible) return;
  if($("secondaryBayBadge")){
    $("secondaryBayBadge").textContent=mode==="camera-2"?"STAGING":"ACTIVE";
  }
  if(mode==="camera-2"){
    const image=$("secondaryBayImage");
    if(secondaryBayPreferences.stagingSource){
      $("secondaryBayUnavailable").hidden=true;
      image.hidden=false;
      image.onload=()=>{
        if($("cameraSlot2Connection")) $("cameraSlot2Connection").textContent="CONNECTED";
      };
      image.onerror=()=>{
        if($("cameraSlot2Connection")) $("cameraSlot2Connection").textContent="DISCONNECTED";
        setSecondaryBayUnavailable("CAMERA 2","Camera disconnected");
      };
      const source="/api/camera-slots/2/stream";
      if(image.getAttribute("src")!==source) image.src=source;
      image.style.objectPosition="50% 50%";
      image.style.transform="none";
    }else{
      setSecondaryBayUnavailable(
        "CAMERA 2",
        "No camera selected\nChoose a source from Manage Cameras"
      );
    }
  }else if(mode==="card-focus"){
    const geometry=smoothedCardFocusGeometry(
      normalizedCardFocusGeometry(window.__rareiqVisionTelemetry||{}),
      context?.verified===true
    );
    if(!geometry){
      secondaryFocusGeometry=null;
      setSecondaryBayUnavailable(
        "Card focus unavailable — unstable card geometry",
        "RareIQ is retaining the full frame until a conservative card-shaped polygon is stable."
      );
    }else{
      const image=$("secondaryBayImage");
      const lockedCapture=context?.verified?truthfulLockedCapture(context):null;
      $("secondaryBayUnavailable").hidden=true;
      image.hidden=false;
      const source=lockedCapture?.url||"/api/camera/stream?viewer=secondary-card-focus";
      if(image.getAttribute("src")!==source) image.src=source;
      image.dataset.frameState=lockedCapture?"locked-capture":"live-active-source";
      applySecondaryCardFocusGeometry(image,geometry);
    }
  }else if(mode==="locked-capture"){
    const capture=truthfulLockedCapture(context);
    if(!capture){
      setSecondaryBayUnavailable("No locked capture","A stable captured frame has not been supplied by the current session.");
    }else{
      const image=$("secondaryBayImage");
      $("secondaryBayUnavailable").hidden=true;
      image.hidden=false;
      if(image.src!==new URL(capture.url,location.href).href) image.src=capture.url;
      if($("secondaryBayStateDetail")) $("secondaryBayStateDetail").textContent=capture.capturedAt?`Captured ${capture.capturedAt}`:"Captured frame";
    }
  }else if(mode==="broadcast-preview"){
    const frame=$("secondaryBroadcastPreview");
    $("secondaryBayUnavailable").hidden=true;
    frame.hidden=false;
    if(!frame.getAttribute("src")) frame.src="/program?embedded=1";
  }else if(mode==="recent-captures"){
    setSecondaryBayUnavailable("No recent capture frames","Recent scan identities are available, but no truthful captured-frame feed is present.");
  }
  renderCameraWorkspace();
}

function setSecondaryBayMode(mode){
  secondaryBayPreferences=normalizeSecondaryBayPreferences({
    ...secondaryBayPreferences,
    mode,
    visible:mode!=="hidden",
    manualPinned:mode!=="hidden",
  });
  saveSecondaryBayPreferences();
  renderSecondaryWorkspaceBay();
  alignScanZone(window.__rareiqVisionTelemetry||{});
}

function setSecondaryStagingSource(value){
  secondaryBayPreferences.stagingSource=value||null;
  cameraWorkspacePreferences.sources["2"]=value||null;
  normalizeSecondarySourcePair();
  saveSecondaryBayPreferences();
  saveCameraWorkspacePreferences();
  renderSecondaryWorkspaceBay();
  renderCameraWorkspace();
}

async function promoteSecondaryStagingSource(){
  const active=$("cameraSelect");
  const staging=secondaryBayPreferences.stagingSource;
  if(!active||!staging||staging===active.value) return;
  const previous=active.value;
  active.value=staging;
  secondaryBayPreferences.stagingSource=previous||null;
  cameraWorkspacePreferences.sources["1"]=staging;
  cameraWorkspacePreferences.sources["2"]=previous||null;
  saveCameraWorkspacePreferences();
  await selectCamera();
}

function loadStudioXPreferences(){
  try{
    return normalizeStudioXPreferences(
      JSON.parse(localStorage.getItem(STUDIOX_PREFERENCES_KEY)||"null")
    );
  }catch{
    return normalizeStudioXPreferences(null);
  }
}

function saveStudioXPreferences(){
  try{
    localStorage.setItem(
      STUDIOX_PREFERENCES_KEY,
      JSON.stringify(studioXPreferences)
    );
  }catch{}
}

function applyWorkspaceLayoutPreset(preset,{persist=true}={}){
  studioXPreferences=normalizeStudioXPreferences({
    ...studioXPreferences,
    layoutPreset:preset,
  });
  document.body.dataset.workspacePreset=studioXPreferences.layoutPreset;
  if($("workspaceLayoutPreset")){
    $("workspaceLayoutPreset").value=studioXPreferences.layoutPreset;
  }
  if(persist) saveStudioXPreferences();
}

function normalizedCardFocusPoints(value){
  const source=Array.isArray(value)
    ? value
    : Array.isArray(value?.points)
    ? value.points
    : [];
  if(source.length!==4) return null;
  const points=source.map(point=>({
    x:Number(Array.isArray(point)?point[0]:point?.x),
    y:Number(Array.isArray(point)?point[1]:point?.y),
  }));
  if(!points.every(point=>Number.isFinite(point.x)&&Number.isFinite(point.y))) return null;
  const normalized=points.every(
    point=>point.x>=-.08&&point.x<=1.08&&point.y>=-.08&&point.y<=1.08
  );
  const frame=visionFrameDimensions(window.__rareiqVisionTelemetry||{});
  if(!normalized&&(!frame.width||!frame.height)) return null;
  const mapped=points.map(point=>({
    x:normalized?Math.max(0,Math.min(1,point.x)):point.x/frame.width,
    y:normalized?Math.max(0,Math.min(1,point.y)):point.y/frame.height,
  }));
  return mapped.every(point=>point.x>=0&&point.x<=1&&point.y>=0&&point.y<=1)
    ? mapped
    : null;
}

function cardFocusSegmentsIntersect(a,b,c,d){
  const orientation=(p,q,r)=>
    (q.x-p.x)*(r.y-p.y)-(q.y-p.y)*(r.x-p.x);
  const abC=orientation(a,b,c);
  const abD=orientation(a,b,d);
  const cdA=orientation(c,d,a);
  const cdB=orientation(c,d,b);
  return abC*abD<0&&cdA*cdB<0;
}

function cardFocusGeometryQuality(points,vision={}){
  /*
   * Frontend-only focus gate. Trading cards are portrait rectangles, so the
   * accepted polygon is deliberately conservative: width/height .58-.84,
   * bounds no wider than 56% or taller than 90% of frame, and polygon area no
   * larger than 56% of the configured scan zone. Recognition still receives
   * the untouched backend geometry.
   */
  if(!Array.isArray(points)||points.length!==4){
    return {valid:false,reason:"missing-corners"};
  }
  if(
    cardFocusSegmentsIntersect(points[0],points[1],points[2],points[3])||
    cardFocusSegmentsIntersect(points[1],points[2],points[3],points[0])
  ){
    return {valid:false,reason:"self-intersecting"};
  }
  const cross=points.map((point,index)=>{
    const next=points[(index+1)%4];
    const after=points[(index+2)%4];
    return (next.x-point.x)*(after.y-next.y)-(next.y-point.y)*(after.x-next.x);
  });
  if(cross.some(value=>Math.abs(value)<.0005)||!(cross.every(value=>value>0)||cross.every(value=>value<0))){
    return {valid:false,reason:"corner-order"};
  }
  const distance=(left,right)=>Math.hypot(right.x-left.x,right.y-left.y);
  const width=(distance(points[0],points[1])+distance(points[3],points[2]))/2;
  const height=(distance(points[1],points[2])+distance(points[0],points[3]))/2;
  const aspect=height?width/height:0;
  const left=Math.min(...points.map(point=>point.x));
  const right=Math.max(...points.map(point=>point.x));
  const top=Math.min(...points.map(point=>point.y));
  const bottom=Math.max(...points.map(point=>point.y));
  const boundsWidth=right-left;
  const boundsHeight=bottom-top;
  const area=Math.abs(points.reduce((sum,point,index)=>{
    const next=points[(index+1)%4];
    return sum+point.x*next.y-next.x*point.y;
  },0)/2);
  const scan=vision?.scan_zone;
  const scanArea=scan
    ? Math.max(.0001,(Number(scan.right)-Number(scan.left))*(Number(scan.bottom)-Number(scan.top)))
    : 1;
  if(aspect<.58||aspect>.84) return {valid:false,reason:"implausible-aspect",aspect};
  if(boundsWidth>.56||boundsHeight>.9) return {valid:false,reason:"implausible-bounds",aspect};
  if(area<.025||area/scanArea>.56) return {valid:false,reason:"implausible-area",aspect};
  return {valid:true,reason:"valid",aspect,area,boundsWidth,boundsHeight};
}

function clearCardFocusGeometry(){
  secondaryFocusGeometry=null;
  lastValidCardFocusGeometry=null;
  lastValidCardFocusAt=0;
  lastCardFocusGeometryReason="unavailable";
}

function visionFrameDimensions(vision={}){
  const actual=vision?.actual_resolution||vision?.frame_shape||[];
  return {
    width:Number(actual[0]||$("cameraFeed")?.naturalWidth||0),
    height:Number(actual[1]||$("cameraFeed")?.naturalHeight||0),
  };
}

function normalizedCardFocusGeometry(vision={}){
  const cornerSource=
    normalizedCardFocusPoints(vision?.card_corners)||
    normalizedCardFocusPoints(vision?.perspective_corners)||
    normalizedCardFocusPoints(vision?.polygon);
  const quality=cornerSource
    ? cardFocusGeometryQuality(cornerSource,vision)
    : {valid:false,reason:"missing-corners"};
  const perspective=quality.valid?cornerSource:null;
  if(cornerSource&&!quality.valid){
    lastCardFocusGeometryReason=quality.reason;
    return null;
  }
  let zone=null;
  if(perspective?.length===4){
    zone={
      left:Math.min(...perspective.map(point=>point.x)),
      top:Math.min(...perspective.map(point=>point.y)),
      right:Math.max(...perspective.map(point=>point.x)),
      bottom:Math.max(...perspective.map(point=>point.y)),
    };
  }else if(vision?.stable===true){
    zone=vision?.detected_card_bounds||vision?.card_bounds||null;
  }
  if(!zone) return null;
  const left=Number(zone.left);
  const top=Number(zone.top);
  const right=Number(zone.right);
  const bottom=Number(zone.bottom);
  if(
    ![left,top,right,bottom].every(Number.isFinite)||
    right<=left||bottom<=top||
    left<0||top<0||right>1||bottom>1
  ) return null;
  const geometry={
    left,top,right,bottom,
    centerX:(left+right)/2,
    centerY:(top+bottom)/2,
    width:right-left,
    height:bottom-top,
    perspective,
  };
  lastValidCardFocusGeometry={...geometry};
  lastValidCardFocusAt=Date.now();
  lastCardFocusGeometryReason="valid";
  return geometry;
}

function smoothedCardFocusGeometry(next,locked=false){
  if(!next){
    if(
      lastValidCardFocusGeometry&&
      Date.now()-lastValidCardFocusAt<=CARD_FOCUS_LAST_VALID_MS
    ){
      return {...lastValidCardFocusGeometry,retained:true};
    }
    return null;
  }
  if(!secondaryFocusGeometry||locked){
    secondaryFocusGeometry={...next};
    return secondaryFocusGeometry;
  }
  const blend=.24;
  secondaryFocusGeometry={
    ...next,
    left:secondaryFocusGeometry.left+(next.left-secondaryFocusGeometry.left)*blend,
    top:secondaryFocusGeometry.top+(next.top-secondaryFocusGeometry.top)*blend,
    right:secondaryFocusGeometry.right+(next.right-secondaryFocusGeometry.right)*blend,
    bottom:secondaryFocusGeometry.bottom+(next.bottom-secondaryFocusGeometry.bottom)*blend,
    centerX:secondaryFocusGeometry.centerX+(next.centerX-secondaryFocusGeometry.centerX)*blend,
    centerY:secondaryFocusGeometry.centerY+(next.centerY-secondaryFocusGeometry.centerY)*blend,
    width:secondaryFocusGeometry.width+(next.width-secondaryFocusGeometry.width)*blend,
    height:secondaryFocusGeometry.height+(next.height-secondaryFocusGeometry.height)*blend,
  };
  return secondaryFocusGeometry;
}

function applySecondaryCardFocusGeometry(image,geometry){
  const content=image?.parentElement;
  const frame=visionFrameDimensions(window.__rareiqVisionTelemetry||{});
  if(!image||!content||!geometry||!frame.width||!frame.height) return false;
  const bayWidth=content.clientWidth;
  const bayHeight=content.clientHeight;
  if(!bayWidth||!bayHeight) return false;
  const containScale=Math.min(bayWidth/frame.width,bayHeight/frame.height);
  const renderedWidth=frame.width*containScale;
  const renderedHeight=frame.height*containScale;
  const letterboxX=(bayWidth-renderedWidth)/2;
  const letterboxY=(bayHeight-renderedHeight)/2;
  const cropWidth=renderedWidth*geometry.width;
  const cropHeight=renderedHeight*geometry.height;
  const cropCenterX=letterboxX+renderedWidth*geometry.centerX;
  const cropCenterY=letterboxY+renderedHeight*geometry.centerY;
  const focusScale=Math.max(1,Math.min(8,Math.min(
    bayWidth*.92/cropWidth,
    bayHeight*.92/cropHeight
  )));
  const translateX=bayWidth/2-cropCenterX*focusScale;
  const translateY=bayHeight/2-cropCenterY*focusScale;
  image.style.setProperty("--secondary-focus-scale",String(focusScale));
  image.style.setProperty("--secondary-focus-translate-x",`${translateX}px`);
  image.style.setProperty("--secondary-focus-translate-y",`${translateY}px`);
  const polygon=(geometry.perspective||[
    {x:geometry.left,y:geometry.top},{x:geometry.right,y:geometry.top},
    {x:geometry.right,y:geometry.bottom},{x:geometry.left,y:geometry.bottom},
  ]).map(point=>`${letterboxX+point.x*renderedWidth}px ${letterboxY+point.y*renderedHeight}px`).join(",");
  image.style.clipPath=`polygon(${polygon})`;
  image.dataset.focusPresentation="tight-card-crop";
  image.dataset.perspectiveCorrection=geometry.perspective?"polygon":"bounds";
  return true;
}

function applyStudioXViewerPresentation(
  context=window.__rareiqCardContext||null,
  vision=window.__rareiqVisionTelemetry||{}
){
  const workspace=document.querySelector(".camera-workspace");
  const feed=$("cameraFeed");
  if(!workspace||!feed) return;
  const geometry=smoothedCardFocusGeometry(
    normalizedCardFocusGeometry(vision),
    context?.verified===true
  );
  const requested=studioXPreferences.viewerMode;
  const stableLock=Boolean(
    context?.verified&&
    context?.presentation?.key==="exact-match"
  );
  const wantsFocus=
    requested==="card-focus"||
    (requested==="auto"&&stableLock);
  const focusAvailable=Boolean(wantsFocus&&geometry);
  const effectiveMode=focusAvailable?"card-focus":"full-frame";
  const focusScale=focusAvailable
    ? Math.max(1,Math.min(3,Math.min(.88/geometry.width,.88/geometry.height)))
    : 1;
  const combinedScale=Math.max(
    .8,
    Math.min(4,focusScale*studioXPreferences.previewZoom)
  );
  const originX=focusAvailable?geometry.centerX*100:50;
  const originY=focusAvailable?geometry.centerY*100:50;
  workspace.dataset.viewerMode=requested;
  workspace.dataset.viewerEffectiveMode=effectiveMode;
  workspace.dataset.focusGeometry=geometry?"available":"unavailable";
  workspace.dataset.perspectiveGeometry=geometry?.perspective?"available":"unavailable";
  workspace.style.setProperty("--studiox-preview-scale",String(combinedScale));
  workspace.style.setProperty("--studiox-preview-origin-x",`${originX}%`);
  workspace.style.setProperty("--studiox-preview-origin-y",`${originY}%`);
  if($("viewerModeSelect")) $("viewerModeSelect").value=requested;
  if($("viewerZoomValue")){
    $("viewerZoomValue").textContent=`${Math.round(studioXPreferences.previewZoom*100)}%`;
  }
  if($("viewerModeStatus")){
    $("viewerModeStatus").textContent=
      requested==="card-focus"&&!geometry
        ? "Card focus unavailable — showing full frame"
        : requested==="auto"
        ? stableLock&&geometry
          ? "Auto · card focus"
          : "Auto · full frame"
        : effectiveMode==="card-focus"
        ? "Card focus"
        : "Full frame";
  }
  updateViewerInspectionHeader(context);
}

function setStudioXViewerMode(mode){
  studioXPreferences=normalizeStudioXPreferences({
    ...studioXPreferences,
    viewerMode:mode,
  });
  saveStudioXPreferences();
  applyStudioXViewerPresentation();
}

function setStudioXPreviewZoom(value){
  studioXPreferences=normalizeStudioXPreferences({
    ...studioXPreferences,
    previewZoom:value,
  });
  saveStudioXPreferences();
  applyStudioXViewerPresentation();
}

function adjustStudioXPreviewZoom(delta){
  setStudioXPreviewZoom(studioXPreferences.previewZoom+delta);
}

function resetStudioXPreviewZoom(){
  setStudioXPreviewZoom(1);
}

function deriveRecognitionPresentation(snapshot={},card=null,candidates=[]){
  const phase=String(
    snapshot?.continuous_state||
    snapshot?.phase||
    snapshot?.status||
    snapshot?.verification_state||
    "IDLE"
  ).toUpperCase();
  const confidence=normalize(
    card?.fused_score??card?.score??card?.confidence??
    snapshot?.overall_confidence??snapshot?.confidence??0
  );
  const verified=Boolean(
    card&&(
      card.verification_strong===true||
      ["database","live_catalog","catalog"].includes(
        String(card.source||"").toLowerCase()
      )
    )
  );
  const hasCandidate=Boolean(card||candidates.length);
  const cardDetected=Boolean(
    snapshot?.card_present===true||
    snapshot?.vision?.visible===true||
    snapshot?.vision?.vision?.visible===true
  );
  if(["ERROR","FAILED"].includes(phase)){
    return {key:"error",state:"error",title:"ERROR",detail:"Recognition is temporarily unavailable.",placeholderTitle:"Recognition Unavailable",confidence};
  }
  if(verified){
    return {key:"exact-match",state:"matched",title:"EXACT MATCH",detail:"Identity verified against the active catalog.",placeholderTitle:"Exact Match",confidence};
  }
  if(
    hasCandidate&&
    ["REVIEW","REVIEW_NEEDED","LOW_CONFIDENCE"].includes(phase)
  ){
    return {key:"review-needed",state:"searching",title:"REVIEW NEEDED",detail:"Candidate evidence needs operator review.",placeholderTitle:"Review Needed",confidence};
  }
  if(["VERIFYING","VERIFICATION","RECOGNIZING"].includes(phase)){
    return {key:"verifying",state:"searching",title:"VERIFYING",detail:"Confirming the strongest identity across recognition signals.",placeholderTitle:"Verifying Card",confidence};
  }
  if(candidates.length){
    return {key:"candidate-found",state:"searching",title:"CANDIDATE FOUND",detail:"RareIQ found reference evidence and is selecting the strongest identity.",placeholderTitle:"Candidate Found",confidence};
  }
  if(["DETECTING","CARD_DETECTED","ACQUIRING"].includes(phase)&&cardDetected){
    return {key:"detecting",state:"searching",title:"DETECTING",detail:"Card geometry is being stabilized inside the scan zone.",placeholderTitle:"Detecting Card",confidence};
  }
  if(cardDetected||!["IDLE","EMPTY","LOST"].includes(phase)){
    return {key:"scanning",state:"searching",title:"SCANNING",detail:"Analyzing artwork, text, and collector data.",placeholderTitle:"Scanning Card",confidence};
  }
  return {key:"ready",state:"idle",title:"READY",detail:"Place a card inside the scan zone.",placeholderTitle:"Ready for Card",confidence:0};
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

    if(result?.provenance?.available===true){
      AUTO_SCREENSHOT_BACKEND_AVAILABLE=true;
      autoScreenshotBackendStatus=result.provenance.status||autoScreenshotBackendStatus;
      renderAutoScreenshotConfig(result.provenance.settings||loadAutoScreenshotConfig());
    }

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

    if(cameraConnectionAvailable===false){
      setCameraDisconnectedPresentation(
        cameraConnectionFailure?.camera||selectedCamera,
        cameraConnectionFailure?.error||"Camera is disconnected"
      );
      return;
    }

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
      null;

    const phase = String(
      snapshot?.continuous_state ||
      snapshot?.phase ||
      raw?.status ||
      snapshot?.verification_state ||
      "IDLE"
    ).toUpperCase();
    const clearInspector =
      ["EMPTY", "CHANGING"].includes(phase) ||
      (phase === "LOST" && !snapshot?.card_present);

    const hadVisibleCard = Boolean(
      previousCardId &&
      $("inspectorMain")?.style.display !== "none"
    );


    const missingCurrentCard =
      !card &&
      !candidates.length;

    if(
      hadVisibleCard &&
      (
        clearInspector ||
        missingCurrentCard
      )
    ){
      return;
    }

    if (clearInspector) {
      snapshot.primary_candidate = null;
      snapshot.provisional_candidate = null;
      candidates.length = 0;
      card = null;

      resetRecognitionPresentation("backend_empty");
      setRecognitionState("idle", "Waiting for a card.");

      setCopilot(
        "STANDBY",
        "Place a card in the scan zone. RareIQ will identify, verify, and explain what it finds."
      );

      return;
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

      const provisionalName=String(
        card?.english_name||card?.printed_name||card?.name||""
      );
      const provisionalLooksUnidentified=
        !verified&&(
          !provisionalName||
          provisionalName.length>70||
          provisionalName.includes("-Set-List-")||
          provisionalName.includes("-Pokemon-")||
          provisionalName.includes("-Pokipair-")||
          /\.(jpg|jpeg|png|webp|avif)$/i.test(provisionalName)
        );
      if(hadVisibleCard&&provisionalLooksUnidentified){
        return;
      }

    const presentation=deriveRecognitionPresentation(
      {...snapshot,status:phase},
      card,
      candidates
    );

    applyRecognitionPresentation(presentation);

    if(phase === "CHANGING"){
      setCopilot("CHANGING","RareIQ invalidated the previous result and is acquiring the replacement card.");
    }else if(phase === "RECOGNIZING"){
      setCopilot("RECOGNIZING","RareIQ is processing the newest card generation.");
    }else if(verified && card){
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
      setCopilot(
        "ANALYZING",
        `RareIQ found reference evidence and is verifying the strongest candidate.`
      );
    }else if(phase !== "IDLE"){
      setCopilot(
        "ANALYZING",
        `RareIQ is <b>${phase.replaceAll("_"," ").toLowerCase()}</b>. Visual, OCR, and database signals are being fused.`
      );
    }else{
      updateConfidenceRing(0);

      setCopilot(
        "STANDBY",
        "Place a card in the scan zone. RareIQ will identify, verify, and explain what it finds."
      );
    }

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
        card.rarity
      ].filter(Boolean).join("  |  ");
      renderIdentityVerdictBadge(presentation,verified);

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
          : "--";

      $("psaValue").textContent =
        psa10 > 0
          ? `$${psa10.toFixed(2)}`
          : "--";

      $("populationValue").textContent =
        population > 0
          ? String(population)
          : "--";

      $("cardStatus").textContent=presentation.title;

      renderExtendedCardData(card,snapshot,confidence,verified);

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
          }  |  ${Math.round(confidence*100)}%`
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
          }  |  ${Math.round(confidence*100)}%`,
          "success"
        );

        if(
          previousCardId &&
          rawValue >= 100
        ){
          triggerHit();
      }
    }else if(clearInspector){
      if(empty) empty.style.display="none";
      if(main) main.style.display="grid";
      $("cardName").textContent="Ready to Scan";
      $("cardMeta").textContent="";
      $("cardArt").innerHTML="";
      resetExtendedCardData();
      updateConfidenceRing(0);
    }

      if(cardId){
        previousCardId = cardId;
      }
    }else{
      if(empty) empty.style.display="none";
      if(main) main.style.display="grid";
    }

    renderPipeline(
      uiPayload.pipeline_stages,
      verified
    );

    updateSharedCardContext(
      deriveSharedCardContext(
        presentation,
        card,
        snapshot,
        candidates
      )
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
      ].join("   |   ");
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
  $("systemStatus").textContent=`${label} started...`;
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
  meta.textContent=[card.set_name,card.collector_number].filter(Boolean).join("  |  ")||"Set details unavailable";
  const confidence=document.createElement("strong");
  confidence.textContent=`${recentScanConfidence(card.confidence)}% confidence`;
  const stamp=document.createElement("time");
  stamp.textContent=card.timestamp?new Date(Number(card.timestamp)*1000).toLocaleString():"Time unavailable";
  const historyPricing=normalizeCardPricing(card);
  const values=document.createElement("p");
  values.className="ui4-history-detail-prices";
  values.textContent=[
    nullableCardNumber(historyPricing.rawMarket)!==null
      ? `Raw ${cardMoney(historyPricing.rawMarket)}`
      : "Raw value unavailable",
    nullableCardNumber(historyPricing.psa10)!==null
      ? `PSA 10 ${cardMoney(historyPricing.psa10)}`
      : "PSA 10 unavailable"
  ].join("  |  ");
  detail.append(name,meta,values,confidence,stamp);
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
    meta.textContent=[card.set_name,card.collector_number].filter(Boolean).join("  |  ")||"Set details unavailable";
    const historyPricing=normalizeCardPricing(card);
    const prices=document.createElement("span");
    prices.className="ui4-history-prices";
    prices.textContent=[
      nullableCardNumber(historyPricing.rawMarket)!==null
        ? `Raw ${cardMoney(historyPricing.rawMarket)}`
        : null,
      nullableCardNumber(historyPricing.psa10)!==null
        ? `PSA 10 ${cardMoney(historyPricing.psa10)}`
        : null
    ].filter(Boolean).join("  |  ")||"Value unavailable";
    identity.append(name,meta,prices);
    const result=document.createElement("span");
    result.className="ui4-history-result";
    const confidence=document.createElement("b");
    confidence.textContent=`${recentScanConfidence(card.confidence)}%`;
    const stamp=document.createElement("time");
    stamp.textContent=card.timestamp?new Date(Number(card.timestamp)*1000).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"}):"--";
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

const STUDIOX_WIDGET_LAYOUT_KEY="rareiq.studiox.widgetLayout.v2";
const STUDIOX_WIDGET_LAYOUT_LEGACY_KEY="rareiq.studiox.widgetLayout.v1";
const STUDIOX_WIDGET_IDS=[
  "identify","ai-grade","market","candidates","details","diagnostics",
  "auto-screenshot"
];
const STUDIOX_WIDGET_TITLES={
  identify:"Identify",
  "ai-grade":"AI Grade",
  market:"Market",
  candidates:"Candidates",
  details:"Details",
  diagnostics:"Diagnostics",
  "auto-screenshot":"Auto Screenshot",
};
const STUDIOX_DEFAULT_WIDGET_LAYOUT={
  version:2,
  order:[...STUDIOX_WIDGET_IDS],
  hidden:[],
  collapsed:["details","diagnostics"],
  pinned:["identify"],
  sizes:{
    identify:"wide",
    "ai-grade":"standard",
    market:"standard",
    candidates:"compact",
    details:"compact",
    diagnostics:"compact",
    "auto-screenshot":"wide",
  },
};
let studioXWidgetLayout=null;

const AUTO_SCREENSHOT_CONFIG_KEY="rareiq.studiox.autoScreenshot.v1";
let AUTO_SCREENSHOT_BACKEND_AVAILABLE=false;
let autoScreenshotBackendStatus={state:"unavailable",event_id:null,error:null};
let autoScreenshotInitialized=false;
const AUTO_SCREENSHOT_WORKFLOWS=[
  "single-card-sales","pack-ripping","pack-battle"
];
const AUTO_SCREENSHOT_TRIGGERS=[
  "manual","exact-match","rarity-threshold","value-threshold","qualifying-hit"
];

function defaultAutoScreenshotConfig(){
  return {
    version:1,
    enabled:false,
    workflowMode:"single-card-sales",
    triggerReason:"manual",
    captureTypes:{fullFrame:true,cardFocus:false,evidenceView:false},
    customerId:null,
    vendorId:null,
    packNumber:null,
    turnNumber:null,
    playerSide:null,
    includeTimestamp:true,
    includeRecognitionEvidence:true,
    minimumConfidence:.9,
    oneCapturePerCard:true,
  };
}

function normalizedOptionalText(value){
  const text=String(value??"").trim();
  return text?text.slice(0,120):null;
}

function normalizedPositiveInteger(value){
  const number=Number(value);
  return Number.isInteger(number)&&number>0?number:null;
}

function normalizeAutoScreenshotConfig(value={}){
  const defaults=defaultAutoScreenshotConfig();
  const workflowMode=AUTO_SCREENSHOT_WORKFLOWS.includes(value.workflowMode)
    ?value.workflowMode
    :defaults.workflowMode;
  const triggerReason=AUTO_SCREENSHOT_TRIGGERS.includes(value.triggerReason)
    ?value.triggerReason
    :defaults.triggerReason;
  const minimum=Number(value.minimumConfidence);
  return {
    ...defaults,
    enabled:AUTO_SCREENSHOT_BACKEND_AVAILABLE&&value.enabled===true,
    workflowMode,
    triggerReason,
    captureTypes:{
      fullFrame:value.captureTypes?.fullFrame!==false,
      cardFocus:value.captureTypes?.cardFocus===true,
      evidenceView:value.captureTypes?.evidenceView===true,
    },
    customerId:normalizedOptionalText(value.customerId),
    vendorId:normalizedOptionalText(value.vendorId),
    packNumber:normalizedPositiveInteger(value.packNumber),
    turnNumber:normalizedPositiveInteger(value.turnNumber),
    playerSide:workflowMode==="pack-battle"&&["player-1","player-2"].includes(value.playerSide)
      ?value.playerSide
      :null,
    includeTimestamp:value.includeTimestamp!==false,
    includeRecognitionEvidence:value.includeRecognitionEvidence!==false,
    minimumConfidence:Number.isFinite(minimum)
      ?Math.min(1,Math.max(0,minimum))
      :defaults.minimumConfidence,
    oneCapturePerCard:true,
  };
}

function loadAutoScreenshotConfig(){
  try{
    return normalizeAutoScreenshotConfig(
      JSON.parse(localStorage.getItem(AUTO_SCREENSHOT_CONFIG_KEY)||"null")||{}
    );
  }catch{
    return defaultAutoScreenshotConfig();
  }
}

function saveAutoScreenshotConfig(config){
  const normalized=normalizeAutoScreenshotConfig(config);
  try{
    localStorage.setItem(AUTO_SCREENSHOT_CONFIG_KEY,JSON.stringify(normalized));
  }catch{}
  return normalized;
}

async function requestAutoScreenshotBackend(path,options={}){
  const response=await fetch(path,{
    cache:"no-store",
    headers:{"Content-Type":"application/json",...(options.headers||{})},
    ...options,
  });
  const payload=await response.json().catch(()=>({ok:false,error:"invalid_response"}));
  if(!response.ok||payload.ok===false){
    throw new Error(payload.message||payload.error||`Request failed (${response.status})`);
  }
  return payload;
}

function autoScreenshotIdentityVerdict(context={}){
  const key=String(context?.presentation?.key||"");
  if(key==="exact-match"&&context.verified===true) return "exact-match";
  if(key==="review-needed") return "review-needed";
  if(["candidate-found","verifying"].includes(key)) return "provisional";
  return "unknown";
}

function autoScreenshotTriggerQualifies(config,context={},options={}){
  const value=normalizeAutoScreenshotConfig(config);
  if(!AUTO_SCREENSHOT_BACKEND_AVAILABLE||!value.enabled) return false;
  const verdict=autoScreenshotIdentityVerdict(context);
  const confidence=Number(context.visualConfidence);
  if(!Number.isFinite(confidence)||confidence<value.minimumConfidence) return false;
  if(value.triggerReason==="manual") return options.manual===true;
  if(value.triggerReason==="exact-match") return verdict==="exact-match";
  if(value.triggerReason==="rarity-threshold"){
    return verdict==="exact-match"&&Boolean(options.truthfulRarity);
  }
  if(value.triggerReason==="value-threshold"){
    return verdict==="exact-match"&&Number.isFinite(options.truthfulMarketValue);
  }
  return verdict==="exact-match"&&options.qualifyingHit===true;
}

function buildAutoScreenshotProvenanceEvent(confirmation,context,config){
  if(!confirmation?.ok||!confirmation.eventId||!confirmation.capturedAt){
    throw new Error("Backend confirmation is required for screenshot provenance.");
  }
  const value=normalizeAutoScreenshotConfig(config);
  const card=context?.card||{};
  return Object.freeze({
    version:1,
    eventId:String(confirmation.eventId),
    sessionId:normalizedOptionalText(confirmation.sessionId),
    customerId:value.customerId,
    vendorId:value.vendorId,
    workflowMode:value.workflowMode,
    packNumber:value.packNumber,
    turnNumber:value.turnNumber,
    playerSide:value.playerSide,
    cardContextId:String(confirmation.cardContextId||context?.identityKey||""),
    cardIdentity:{
      cardId:normalizedOptionalText(card.id),
      englishName:normalizedOptionalText(card.english_name||card.canonical_name),
      printedName:normalizedOptionalText(card.printed_name||card.name),
      set:normalizedOptionalText(card.set_name||card.set_id),
      localCardId:normalizedOptionalText(card.collector_number),
      officialNumber:normalizedOptionalText(context?.officialCollectorNumber),
      identityVerdict:autoScreenshotIdentityVerdict(context),
      visualConfidence:Number.isFinite(Number(context?.visualConfidence))
        ?Number(context.visualConfidence)
        :null,
    },
    triggerReason:value.triggerReason,
    capturedAt:String(confirmation.capturedAt),
    cameraSource:normalizedOptionalText(confirmation.cameraSource),
    assets:{
      fullFrame:normalizedOptionalText(confirmation.assets?.fullFrame),
      cardFocus:normalizedOptionalText(confirmation.assets?.cardFocus),
      evidenceView:normalizedOptionalText(confirmation.assets?.evidenceView),
      clipId:normalizedOptionalText(confirmation.assets?.clipId),
    },
  });
}

function createAutoScreenshotCorrectionRevision(originalEvent,confirmation,cardIdentity){
  if(!originalEvent?.eventId||!confirmation?.ok||!confirmation?.revisionId){
    throw new Error("Confirmed revision metadata is required.");
  }
  return Object.freeze({
    originalEventId:String(originalEvent.eventId),
    revisionId:String(confirmation.revisionId),
    revisedAt:String(confirmation.revisedAt||""),
    cardIdentity:{...cardIdentity},
  });
}

function readAutoScreenshotForm(){
  return normalizeAutoScreenshotConfig({
    enabled:$("autoScreenshotEnabled")?.checked===true,
    workflowMode:$("autoScreenshotWorkflow")?.value,
    triggerReason:$("autoScreenshotTrigger")?.value,
    captureTypes:{
      fullFrame:$("autoScreenshotFullFrame")?.checked===true,
      cardFocus:$("autoScreenshotCardFocus")?.checked===true,
      evidenceView:$("autoScreenshotEvidenceView")?.checked===true,
    },
    customerId:$("autoScreenshotCustomerId")?.value,
    vendorId:$("autoScreenshotVendorId")?.value,
    packNumber:$("autoScreenshotPackNumber")?.value,
    turnNumber:$("autoScreenshotTurnNumber")?.value,
    playerSide:$("autoScreenshotPlayerSide")?.value,
    includeTimestamp:$("autoScreenshotTimestamp")?.checked===true,
    includeRecognitionEvidence:$("autoScreenshotEvidence")?.checked===true,
    minimumConfidence:Number($("autoScreenshotMinimumConfidence")?.value)/100,
  });
}

function renderAutoScreenshotConfig(config=loadAutoScreenshotConfig()){
  const value=normalizeAutoScreenshotConfig(config);
  const assignments={
    autoScreenshotWorkflow:value.workflowMode,
    autoScreenshotTrigger:value.triggerReason,
    autoScreenshotCustomerId:value.customerId||"",
    autoScreenshotVendorId:value.vendorId||"",
    autoScreenshotPackNumber:value.packNumber||"",
    autoScreenshotTurnNumber:value.turnNumber||"",
    autoScreenshotPlayerSide:value.playerSide||"",
    autoScreenshotMinimumConfidence:Math.round(value.minimumConfidence*100),
  };
  Object.entries(assignments).forEach(([id,fieldValue])=>{
    if($(id)) $(id).value=fieldValue;
  });
  if($("autoScreenshotEnabled")){
    $("autoScreenshotEnabled").checked=value.enabled;
    $("autoScreenshotEnabled").disabled=!AUTO_SCREENSHOT_BACKEND_AVAILABLE;
  }
  if($("autoScreenshotFullFrame")) $("autoScreenshotFullFrame").checked=value.captureTypes.fullFrame;
  if($("autoScreenshotCardFocus")) $("autoScreenshotCardFocus").checked=value.captureTypes.cardFocus;
  if($("autoScreenshotEvidenceView")) $("autoScreenshotEvidenceView").checked=value.captureTypes.evidenceView;
  if($("autoScreenshotTimestamp")) $("autoScreenshotTimestamp").checked=value.includeTimestamp;
  if($("autoScreenshotEvidence")) $("autoScreenshotEvidence").checked=value.includeRecognitionEvidence;
  if($("autoScreenshotManualCapture")) $("autoScreenshotManualCapture").disabled=!AUTO_SCREENSHOT_BACKEND_AVAILABLE;
  const state=AUTO_SCREENSHOT_BACKEND_AVAILABLE
    ?String(autoScreenshotBackendStatus.state||(value.enabled?"armed":"configured"))
    :"unavailable";
  const labels={configured:"Configured",armed:"Armed",capturing:"Capturing",saved:"Saved",error:"Error",unavailable:"Unavailable"};
  if($("autoScreenshotState")) $("autoScreenshotState").textContent=labels[state]||"Configured";
  if($("autoScreenshotStatus")){
    $("autoScreenshotStatus").textContent=!AUTO_SCREENSHOT_BACKEND_AVAILABLE
      ?"Screenshot capture engine not connected"
      :autoScreenshotBackendStatus.error
      ?String(autoScreenshotBackendStatus.error)
      :autoScreenshotBackendStatus.event_id
      ?`Saved event ${autoScreenshotBackendStatus.event_id}`
      :value.enabled
      ?"Automatic provenance capture armed"
      :"Manual screenshot available";
  }
  setStudioXWidgetState("auto-screenshot",state);
  return value;
}

async function persistAutoScreenshotSettings(config){
  const payload=await requestAutoScreenshotBackend("/api/provenance/settings",{
    method:"PUT",
    body:JSON.stringify({settings:config}),
  });
  autoScreenshotBackendStatus=payload.status||autoScreenshotBackendStatus;
  return saveAutoScreenshotConfig(payload.settings||config);
}

async function manualAutoScreenshotCapture(){
  const button=$("autoScreenshotManualCapture");
  if(button) button.disabled=true;
  autoScreenshotBackendStatus={state:"capturing",event_id:null,error:null};
  renderAutoScreenshotConfig();
  try{
    const result=await requestAutoScreenshotBackend("/api/provenance/capture",{method:"POST"});
    autoScreenshotBackendStatus={state:"saved",event_id:result.eventId,error:null};
  }catch(error){
    autoScreenshotBackendStatus={state:"error",event_id:null,error:String(error?.message||error)};
  }finally{
    renderAutoScreenshotConfig();
  }
}

async function initializeAutoScreenshotConfiguration(){
  const form=$("autoScreenshotForm");
  if(!form||autoScreenshotInitialized) return;
  autoScreenshotInitialized=true;
  // Bind the manual action before awaiting capability discovery. The
  // recognition poll may enable this control independently, so its handler
  // must not depend on the rest of the Studio X shell initializing cleanly.
  $("autoScreenshotManualCapture")?.addEventListener("click",manualAutoScreenshotCapture);
  renderAutoScreenshotConfig();
  try{
    const payload=await requestAutoScreenshotBackend("/api/provenance/settings");
    AUTO_SCREENSHOT_BACKEND_AVAILABLE=payload.available===true;
    autoScreenshotBackendStatus=payload.status||autoScreenshotBackendStatus;
    renderAutoScreenshotConfig(saveAutoScreenshotConfig(payload.settings||{}));
  }catch{
    AUTO_SCREENSHOT_BACKEND_AVAILABLE=false;
    renderAutoScreenshotConfig();
  }
  form.addEventListener("change",async()=>{
    const config=saveAutoScreenshotConfig(readAutoScreenshotForm());
    renderAutoScreenshotConfig(config);
    if(!AUTO_SCREENSHOT_BACKEND_AVAILABLE) return;
    try{
      renderAutoScreenshotConfig(await persistAutoScreenshotSettings(config));
    }catch(error){
      autoScreenshotBackendStatus={state:"error",event_id:null,error:String(error?.message||error)};
      renderAutoScreenshotConfig(config);
    }
  });
}

function defaultStudioXWidgetLayout(){
  return {
    version:STUDIOX_DEFAULT_WIDGET_LAYOUT.version,
    order:[...STUDIOX_DEFAULT_WIDGET_LAYOUT.order],
    hidden:[...STUDIOX_DEFAULT_WIDGET_LAYOUT.hidden],
    collapsed:[...STUDIOX_DEFAULT_WIDGET_LAYOUT.collapsed],
    pinned:[...STUDIOX_DEFAULT_WIDGET_LAYOUT.pinned],
    sizes:{...STUDIOX_DEFAULT_WIDGET_LAYOUT.sizes},
  };
}

function normalizeStudioXWidgetLayout(value){
  if(!value||![1,2].includes(value.version)) return defaultStudioXWidgetLayout();
  const validList=list=>Array.isArray(list)
    ? [...new Set(list.filter(id=>STUDIOX_WIDGET_IDS.includes(id)))]
    : [];
  const savedOrder=validList(value.order);
  const validSizes=["compact","standard","wide"];
  const sizes={...STUDIOX_DEFAULT_WIDGET_LAYOUT.sizes};
  if(value.version===2&&value.sizes&&typeof value.sizes==="object"){
    STUDIOX_WIDGET_IDS.forEach(id=>{
      if(validSizes.includes(value.sizes[id])) sizes[id]=value.sizes[id];
    });
  }
  return {
    version:2,
    order:[
      ...savedOrder,
      ...STUDIOX_WIDGET_IDS.filter(id=>!savedOrder.includes(id)),
    ],
    hidden:validList(value.hidden),
    collapsed:validList(value.collapsed),
    pinned:validList(value.pinned),
    sizes,
  };
}

function loadStudioXWidgetLayout(){
  try{
    const savedV2=localStorage.getItem(STUDIOX_WIDGET_LAYOUT_KEY);
    const savedV1=localStorage.getItem(STUDIOX_WIDGET_LAYOUT_LEGACY_KEY);
    return normalizeStudioXWidgetLayout(
      JSON.parse(savedV2||savedV1||"null")
    );
  }catch{
    return defaultStudioXWidgetLayout();
  }
}

function saveStudioXWidgetLayout(){
  try{
    localStorage.setItem(
      STUDIOX_WIDGET_LAYOUT_KEY,
      JSON.stringify(studioXWidgetLayout)
    );
  }catch{}
}

function widgetStateLabel(widget){
  return String(widget?.dataset.widgetState||"empty")
    .replaceAll("-"," ");
}

function ensureStudioXWidgetChrome(widget){
  if(widget.querySelector(":scope > .studiox-widget-header")) return;
  const id=widget.dataset.studioxWidget;
  const header=document.createElement("header");
  header.className="studiox-widget-header";
  header.innerHTML=`
    <button class="studiox-widget-focus" type="button" data-widget-focus="${id}">
      <span>${STUDIOX_WIDGET_TITLES[id]||id}</span>
      <small data-widget-status>${widgetStateLabel(widget)}</small>
    </button>
    <div class="studiox-widget-controls">
      <button type="button" data-widget-action="pin" aria-label="Pin ${STUDIOX_WIDGET_TITLES[id]}">Pin</button>
      <button type="button" data-widget-action="up" aria-label="Move ${STUDIOX_WIDGET_TITLES[id]} up">↑</button>
      <button type="button" data-widget-action="down" aria-label="Move ${STUDIOX_WIDGET_TITLES[id]} down">↓</button>
      <button type="button" data-widget-action="size" aria-label="Change ${STUDIOX_WIDGET_TITLES[id]} size">Size</button>
      <button type="button" data-widget-action="collapse" aria-label="Collapse ${STUDIOX_WIDGET_TITLES[id]}">Collapse</button>
    </div>
  `;
  widget.prepend(header);
}

function applyStudioXWidgetLayout({persist=false}={}){
  const workspace=$("widgetWorkspace");
  if(!workspace) return;
  studioXWidgetLayout=normalizeStudioXWidgetLayout(
    studioXWidgetLayout||loadStudioXWidgetLayout()
  );
  const pinned=studioXWidgetLayout.order.filter(
    id=>studioXWidgetLayout.pinned.includes(id)
  );
  const unpinned=studioXWidgetLayout.order.filter(
    id=>!studioXWidgetLayout.pinned.includes(id)
  );
  studioXWidgetLayout.order=[...pinned,...unpinned];
  studioXWidgetLayout.order.forEach(id=>{
    const widget=workspace.querySelector(`[data-studiox-widget="${id}"]`);
    if(!widget) return;
    ensureStudioXWidgetChrome(widget);
    workspace.appendChild(widget);
    widget.hidden=studioXWidgetLayout.hidden.includes(id);
    widget.classList.toggle(
      "is-collapsed",
      studioXWidgetLayout.collapsed.includes(id)
    );
    widget.classList.toggle(
      "is-pinned",
      studioXWidgetLayout.pinned.includes(id)
    );
    widget.dataset.widgetSize=studioXWidgetLayout.sizes[id];
    const collapse=widget.querySelector('[data-widget-action="collapse"]');
    if(collapse){
      const collapsed=widget.classList.contains("is-collapsed");
      collapse.textContent=collapsed?"Expand":"Collapse";
      collapse.setAttribute("aria-expanded",collapsed?"false":"true");
    }
    const pin=widget.querySelector('[data-widget-action="pin"]');
    if(pin){
      const isPinned=widget.classList.contains("is-pinned");
      pin.textContent=isPinned?"Unpin":"Pin";
      pin.setAttribute("aria-pressed",isPinned?"true":"false");
    }
    const size=widget.querySelector('[data-widget-action="size"]');
    if(size) size.textContent=studioXWidgetLayout.sizes[id];
  });
  document.querySelectorAll("[data-widget-visibility]").forEach(input=>{
    input.checked=!studioXWidgetLayout.hidden.includes(
      input.dataset.widgetVisibility
    );
  });
  if(persist) saveStudioXWidgetLayout();
}

function updateStudioXWidgetLayout(id,action,value=null){
  if(!STUDIOX_WIDGET_IDS.includes(id)) return;
  studioXWidgetLayout=normalizeStudioXWidgetLayout(
    studioXWidgetLayout||loadStudioXWidgetLayout()
  );
  if(action==="visibility"){
    studioXWidgetLayout.hidden=studioXWidgetLayout.hidden.filter(item=>item!==id);
    if(value===false) studioXWidgetLayout.hidden.push(id);
  }else if(action==="collapse"){
    const collapsed=studioXWidgetLayout.collapsed.includes(id);
    studioXWidgetLayout.collapsed=studioXWidgetLayout.collapsed.filter(item=>item!==id);
    if(!collapsed) studioXWidgetLayout.collapsed.push(id);
  }else if(action==="pin"){
    const pinned=studioXWidgetLayout.pinned.includes(id);
    studioXWidgetLayout.pinned=studioXWidgetLayout.pinned.filter(item=>item!==id);
    if(!pinned) studioXWidgetLayout.pinned.push(id);
  }else if(action==="size"){
    const sizes=["compact","standard","wide"];
    const current=sizes.indexOf(studioXWidgetLayout.sizes[id]);
    studioXWidgetLayout.sizes[id]=sizes[(current+1)%sizes.length];
  }else if(action==="up"||action==="down"){
    const index=studioXWidgetLayout.order.indexOf(id);
    const target=index+(action==="up"?-1:1);
    if(index>=0&&target>=0&&target<studioXWidgetLayout.order.length){
      [
        studioXWidgetLayout.order[index],
        studioXWidgetLayout.order[target],
      ]=[
        studioXWidgetLayout.order[target],
        studioXWidgetLayout.order[index],
      ];
    }
  }
  applyStudioXWidgetLayout({persist:true});
}

function resetStudioXWidgetLayout(){
  studioXWidgetLayout=defaultStudioXWidgetLayout();
  applyStudioXWidgetLayout({persist:true});
}

function setPremiumIntelligenceTab(name="identify"){
  const widget=document.querySelector(`[data-studiox-widget="${name}"]`);
  if(!widget) return;
  document.querySelectorAll("[data-studiox-widget]").forEach(node=>{
    node.classList.toggle("is-focused",node===widget);
  });
  widget.querySelector(".studiox-widget-focus")?.focus({preventScroll:true});
}

function deriveSharedCardContext(presentation,card=null,snapshot={},candidates=[]){
  const grading=
    snapshot?.ai_grade||
    snapshot?.grading||
    card?.ai_grade||
    card?.grading||
    null;
  const allowedGradeStates=[
    "unavailable","waiting-for-stable-capture","front-analysis-ready",
    "back-image-required","analyzing","error"
  ];
  let gradeState=String(grading?.state||"").toLowerCase();
  if(!allowedGradeStates.includes(gradeState)){
    gradeState=["detecting","scanning","candidate-found","verifying"].includes(presentation.key)
      ? "waiting-for-stable-capture"
      : "unavailable";
  }
  const verified=presentation.key==="exact-match";
  return {
    revision:Number(snapshot?.revision||0),
    identityKey:String(
      card?.identity_override_key||
      card?.id||
      `${card?.set_id||""}:${card?.collector_number||""}`
    ),
    presentation:{...presentation},
    card:card||null,
    candidates:Array.isArray(candidates)?[...candidates]:[],
    verified,
    visualConfidence:normalize(
      card?.visual_score??
      card?.artwork_score??
      presentation?.confidence??
      0
    ),
    officialCollectorNumber:
      card?.official_collector_number||
      snapshot?.official_collector_number||
      null,
    market:deriveMarketPresentation(card||{}),
    snapshot:{...snapshot},
    grading,
    gradeState,
  };
}

function setStudioXWidgetState(id,state){
  const widget=document.querySelector(`[data-studiox-widget="${id}"]`);
  if(!widget) return;
  widget.dataset.widgetState=state;
  const status=widget.querySelector("[data-widget-status]");
  if(status) status.textContent=String(state).replaceAll("-"," ");
}

function deriveLiveAnalysisSteps(context){
  const snapshot=context.snapshot||{};
  const vision=snapshot?.vision?.vision||snapshot?.vision||{};
  const presentation=context.presentation.key;
  const active=!["ready","exact-match"].includes(presentation);
  const detected=Boolean(
    snapshot.card_present===true||
    vision.visible===true||
    context.card||
    context.candidates.length
  );
  const geometryStable=Boolean(
    vision.stable===true||
    Number(vision.stable_frames||0)>=Number(vision.stable_target||Infinity)
  );
  const artworkEvidence=Boolean(
    context.candidates.length||
    context.card?.visual_score||
    context.card?.artwork_score||
    snapshot?.artwork_index?.score
  );
  const collectorEvidence=Boolean(
    snapshot.collector_number||
    context.card?.collector_number
  );
  const error=presentation==="error";
  return {
    detection:error?"error":detected?"complete":active?"active":"pending",
    geometry:error?"error":geometryStable?"complete":detected?"active":"pending",
    artwork:error?"error":artworkEvidence?"complete":detected&&["scanning","candidate-found","verifying","review-needed"].includes(presentation)?"active":"pending",
    collector:error?"error":collectorEvidence?"complete":artworkEvidence&&["scanning","candidate-found","verifying","review-needed"].includes(presentation)?"active":"pending",
    catalog:error?"error":context.verified?"complete":["candidate-found","verifying","review-needed"].includes(presentation)?"active":"pending",
  };
}

function hasTruthfulRecognizedIdentity(context){
  const card=context?.card;
  if(!card) return false;
  const name=firstCardValue(card,["english_name","canonical_name","printed_name","name"]);
  const locator=firstCardValue(card,["collector_number","official_collector_number","set_id","set_name"]);
  return Boolean(
    name&&locator&&
    ["candidate-found","review-needed","exact-match"].includes(context.presentation.key)
  );
}

function renderLiveAnalysisTimeline(context){
  const timeline=$("liveAnalysisTimeline");
  const header=$("cardContextHeader");
  const pending=$("identityPendingPlaceholder");
  if(!timeline||!header||!pending) return;
  const recognized=context.verified||hasTruthfulRecognizedIdentity(context);
  const scanning=!recognized&&!["ready","exact-match"].includes(context.presentation.key);
  const state=context.presentation.key;
  const currentView=document.querySelector(".ui4-current-card-view");
  const inspectorMain=$("inspectorMain");
  if(currentView) currentView.dataset.presentationState=state;
  if(inspectorMain) inspectorMain.dataset.presentationState=state;
  timeline.hidden=!scanning;
  pending.hidden=recognized;
  header.hidden=!recognized;
  header.inert=!recognized;
  if($("liveAnalysisTitle")){
    $("liveAnalysisTitle").textContent=context.presentation.placeholderTitle;
  }
  if($("liveAnalysisState")){
    $("liveAnalysisState").textContent=context.presentation.title;
  }
  if($("liveAnalysisDetail")){
    $("liveAnalysisDetail").textContent=context.presentation.detail;
  }
  if($("identityPendingTitle")) $("identityPendingTitle").textContent="IDENTITY PENDING";
  if($("identityPendingDetail")){
    $("identityPendingDetail").textContent=
      context.presentation.key==="ready"
        ?"Waiting for card"
        : context.presentation.key==="review-needed"
        ?"Waiting for operator confirmation"
        :"Waiting for catalog confirmation";
  }
  const labels={
    pending:"Pending",
    active:"In progress",
    complete:"Complete",
    unavailable:"Unavailable",
    error:"Error",
  };
  const steps=deriveLiveAnalysisSteps(context);
  Object.entries(steps).forEach(([name,state])=>{
    const row=timeline.querySelector(`[data-analysis-step="${name}"]`);
    if(!row) return;
    row.dataset.stepState=state;
    const label=row.querySelector("b");
    if(label) label.textContent=labels[state];
  });
}

function renderAuthoritativeCardContextHeader(context){
  renderLiveAnalysisTimeline(context);
  renderIdentityVerdictBadge(context.presentation,context.verified);
  if(context.verified||hasTruthfulRecognizedIdentity(context)) return;
  const presentation=context.presentation;
  if($("resultEyebrow")) $("resultEyebrow").textContent="Live Recognition";
  if($("cardName")){
    $("cardName").textContent=
      presentation.key==="ready"
        ? "Ready for card"
        : presentation.placeholderTitle;
  }
  if($("cardMeta")) $("cardMeta").textContent=presentation.detail;
  if($("cardStatus")) $("cardStatus").textContent=presentation.title;
  if($("cardValue")) $("cardValue").textContent="Waiting for confirmed identity";
  if($("cardArt")) $("cardArt").replaceChildren();
  resetExtendedCardData();
}

function renderIdentityVerdictBadge(presentation={},verified=false){
  const badge=$("identityVerdictBadge");
  if(!badge) return;
  const provisional=!verified&&[
    "candidate-found","verifying","review-needed"
  ].includes(presentation.key);
  badge.hidden=!(verified||provisional);
  badge.dataset.verdict=verified?"exact-match":"provisional";
  badge.textContent=verified?"EXACT MATCH":"PROVISIONAL";
}

function renderIdentifyWidget(context){
  const scanning=!context.verified&&!["ready","error"].includes(context.presentation.key);
  setCardText(
    "identifyCatalogStatus",
    context.verified
      ?"Exact"
      : scanning
      ? context.presentation.key==="verifying"
        ?"Catalog verification in progress"
        :"Recognition evidence gathering"
      :"Waiting for card"
  );
  setCardText(
    "identifyVisualConfidence",
    `${Math.round(context.visualConfidence*100)}%`
  );
  setCardText(
    "identifyAcceptanceEvidence",
    !context.card
      ? scanning
        ? "Waiting for stronger evidence"
        : "Not available"
      : context.verified
      ? "Verified catalog identity"
      : "Operator review required"
  );
  const identifyWidget=document.querySelector('[data-studiox-widget="identify"]');
  if(identifyWidget){
    identifyWidget.dataset.identityVerdict=
      context.verified?"verified":scanning?"pending":context.card?"provisional":"empty";
  }
  const evidence=$("identifyEvidence");
  if(evidence){
    const card=context.card||{};
    const artworkScore=firstCardValue(card,["visual_score","artwork_score"]);
    const rows=[
      [
        "Artwork match",
        artworkScore!==null
          ? `${context.verified?"Strong · ":""}${Math.round(normalize(artworkScore)*100)}% visual confidence`
          : null,
      ],
      ["Collector number",firstCardValue(card,["collector_number","card_number"])?(context.verified?"Confirmed":firstCardValue(card,["collector_number","card_number"])):null],
      ["Set confirmation",firstCardValue(card,["set_name","set","set_code","set_id"])?(context.verified?"Confirmed":firstCardValue(card,["set_name","set","set_code","set_id"])):null],
      ["Language",firstCardValue(card,["language","language_name","language_code"])?(context.verified?"Confirmed":firstCardValue(card,["language","language_name","language_code"])):null],
      ["Variant",firstCardValue(card,["variant","variant_name","rarity_variant"])],
    ].filter(([,value])=>value!==null&&value!==undefined&&String(value).trim());
    evidence.dataset.summaryLabel=context.verified?"Identity verified":"Identity evidence";
    evidence.replaceChildren();
    rows.forEach(([label,value])=>{
      const row=document.createElement("div");
      const name=document.createElement("span");
      const detail=document.createElement("b");
      name.textContent=label;
      detail.textContent=String(value);
      row.append(name,detail);
      evidence.appendChild(row);
    });
    evidence.hidden=!rows.length;
  }
  setStudioXWidgetState(
    "identify",
    context.verified
      ?"available"
      : scanning
      ?"verification-in-progress"
      : context.card
      ?"review-needed"
      :"empty"
  );
}

function renderAIGradeWidget(context){
  const grading=context.grading||{};
  const values={
    aiGradeCentering:grading.centering,
    aiGradeCorners:grading.corners,
    aiGradeEdges:grading.edges,
    aiGradeSurface:grading.surface,
    aiGradeRange:grading.estimated_range,
    aiGradeConfidence:grading.confidence,
  };
  setCardText(
    "aiGradeState",
    context.gradeState==="waiting-for-stable-capture"
      ?"Waiting for a stable card capture"
      : context.gradeState==="unavailable"
      ?"Unavailable"
      : context.gradeState.replaceAll("-"," "),
    "Unavailable"
  );
  Object.entries(values).forEach(([id,value])=>{
    setCardText(id,value,"Pending");
  });
  const gradeMetrics=$("aiGradeMetrics");
  if(gradeMetrics){
    gradeMetrics.hidden=!Object.values(values).some(
      value=>value!==undefined&&value!==null&&value!==""
    );
  }
  const emptyDetail=$("aiGradeEmptyDetail");
  if(emptyDetail){
    const hasMetrics=Object.values(values).some(
      value=>value!==undefined&&value!==null&&value!==""
    );
    emptyDetail.hidden=hasMetrics;
    emptyDetail.textContent=
      context.gradeState==="waiting-for-stable-capture"
        ?"Waiting for a stable card capture."
        :"AI Grade is unavailable because no grading provider is connected.";
  }
  setStudioXWidgetState("ai-grade",context.gradeState);
}

function renderMarketWidget(context){
  const scanning=!context.verified&&!["ready","error"].includes(context.presentation.key);
  const state=context.card&&context.verified?context.market.key:"identity-pending";
  const hasMetrics=state==="available";
  const messages={
    pending:"Retrieving market intelligence",
    available:"Current public market data",
    "no-data":"No verified market data is available for this card.",
    "provider-error":"Market provider unavailable.",
    "identity-pending":"Waiting for confirmed identity",
  };
  setCardText("marketWidgetState",messages[state],"No public market data.");
  const marketWidget=document.querySelector('[data-studiox-widget="market"]');
  marketWidget?.querySelectorAll(".ui4-price-primary,.ui4-price-grid").forEach(node=>{
    node.hidden=!hasMetrics;
  });
  const footnote=marketWidget?.querySelector(".ui4-price-footnote");
  if(footnote){
    footnote.hidden=!["available","pending"].includes(state);
  }
  if($("cardValue")){
    $("cardValue").textContent=
      state==="identity-pending"
        ?"Waiting for confirmed identity"
        : state==="pending"
        ?"Retrieving market intelligence"
        : state==="no-data"&&context.verified
        ?"No public market data"
        : state==="provider-error"
        ?"Market provider unavailable"
        : $("cardValue").textContent;
  }
  setStudioXWidgetState(
    "market",
    state==="pending"
      ? "fetching"
      : state==="provider-error"
      ? "provider-unavailable"
      : state
  );
}

function renderCandidatesWidget(context){
  const count=context.candidates.length;
  const searching=!context.verified&&["detecting","scanning","candidate-found","verifying"].includes(context.presentation.key);
  setCardText(
    "candidateWidgetSummary",
    count
      ? `${count} alternative candidate${count===1?"":"s"} available for review.`
      : searching
      ? "Searching catalog candidates"
      : context.verified
      ? "Exact identity verified. No alternative candidates require review."
      : context.presentation.key==="review-needed"
      ? "No verified candidates found"
      : "No alternative candidates are available."
  );
  setStudioXWidgetState(
    "candidates",
    context.presentation.key==="error"
      ? "error"
      : context.presentation.key==="review-needed"
      ? "review-needed"
      : count
      ? "alternatives-available"
      : searching
      ? "searching"
      : context.verified
      ? "verified"
      : "no-candidates"
  );
  const reviewButton=$("candidateReviewButton");
  if(reviewButton){
    reviewButton.hidden=!(count>0&&context.presentation.key==="review-needed");
  }
}

function renderDetailsWidget(context){
  const widget=document.querySelector('[data-studiox-widget="details"]');
  const available=context.verified&&context.card;
  if(widget&&!available) widget.dataset.widgetSize="compact";
  setStudioXWidgetState("details",available?"available":"empty");
}

function renderDiagnosticsWidget(context){
  setCardText("diagnosticRecognitionState",context.presentation.title);
  setCardText(
    "diagnosticVisualConfidence",
    `${Math.round(context.visualConfidence*100)}%`
  );
  setCardText(
    "diagnosticCatalogVerification",
    context.verified?"Verified":"Not verified"
  );
  setCardText(
    "diagnosticPipelineState",
    context.presentation.key.replaceAll("-"," ")
  );
  setStudioXWidgetState(
    "diagnostics",
    context.presentation.key==="error"?"error":"available"
  );
}

function renderAutoScreenshotWidget(){
  renderAutoScreenshotConfig();
}

const STUDIOX_WIDGET_RENDERERS={
  identify:renderIdentifyWidget,
  "ai-grade":renderAIGradeWidget,
  market:renderMarketWidget,
  candidates:renderCandidatesWidget,
  details:renderDetailsWidget,
  diagnostics:renderDiagnosticsWidget,
  "auto-screenshot":renderAutoScreenshotWidget,
};

function updateSharedCardContext(context){
  window.__rareiqCardContext=context;
  document.body.dataset.presentationState=context.presentation.key;
  applyStudioXExactMatchMoment(context);
  updateViewerInspectionHeader(context);
  applyRecognitionPresentation(context.presentation);
  renderAuthoritativeCardContextHeader(context);
  applyStudioXViewerPresentation(
    context,
    window.__rareiqVisionTelemetry||{}
  );
  renderSecondaryWorkspaceBay(context);
  const actionable=context.verified||hasTruthfulRecognizedIdentity(context);
  ["approveButton","rejectButton","detailsButton"].forEach(id=>{
    const button=$(id);
    if(button) button.disabled=!actionable;
  });
  if($("nextClearButton")) $("nextClearButton").disabled=false;
  Object.entries(STUDIOX_WIDGET_RENDERERS).forEach(([id,renderer])=>{
    try{
      renderer(context);
    }catch(error){
      console.warn(`Studio X widget ${id} failed`,error);
      setStudioXWidgetState(id,"error");
    }
  });
  document.dispatchEvent(
    new CustomEvent("rareiq:card-context",{detail:context})
  );
}

function applyStudioXExactMatchMoment(context={}){
  const exact=context?.presentation?.key==="exact-match"&&context?.verified===true;
  if(!exact){
    document.body.classList.remove("studiox-exact-match-moment");
    if(["ready","detecting","scanning"].includes(context?.presentation?.key)){
      studioXExactMatchMomentKey=null;
    }
    return;
  }
  const key=[
    currentServerSessionId||"server",
    context?.snapshot?.generation??"generation",
    context?.identityKey||"card",
  ].join(":");
  if(key===studioXExactMatchMomentKey) return;
  studioXExactMatchMomentKey=key;
  clearTimeout(studioXExactMatchMomentTimer);
  document.body.classList.remove("studiox-exact-match-moment");
  requestAnimationFrame(()=>{
    document.body.classList.add("studiox-exact-match-moment");
    studioXExactMatchMomentTimer=setTimeout(()=>{
      document.body.classList.remove("studiox-exact-match-moment");
    },720);
  });
}

function initializeStudioXUI4(){
  if(document.body.dataset.ui4Initialized==="true") return;
  const camera=document.querySelector(".camera-workspace");
  const inspector=document.querySelector(".inspector");
  const inspectorMount=document.querySelector(".ui4-inspector-column");
  const pipeline=document.querySelector(".pipeline-rail");
  const dock=document.querySelector(".dock");
  const toolbar=document.querySelector(".toolbar");
  const appbar=document.querySelector(".appbar");
  if(!camera||!inspector||!inspectorMount||!pipeline||!dock||!toolbar||!appbar) return;
  document.body.dataset.ui4Initialized="true";

  if(inspector.parentElement!==inspectorMount) inspectorMount.appendChild(inspector);
  if(pipeline.parentElement!==camera) camera.appendChild(pipeline);
  dock.classList.add("ui4-diagnostics-drawer");
  dock.setAttribute("aria-hidden","true");
  if(dock.parentElement!==camera) camera.appendChild(dock);

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
  if(recovery) recovery.textContent="Reconnect Camera";
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
  const actionsRow=toolbar.querySelector(".premium-actions-row")||toolbar;
  actionsRow.append(diagnosticsButton,healthButton);

  const healthPopover=document.createElement("div");
  healthPopover.className="ui4-health-popover";
  healthPopover.setAttribute("aria-hidden","true");
  const lowFrequency=[
    toolbar.querySelector('[onclick="startSelectedCamera()"]'),
    toolbar.querySelector('[onclick="stopCamera()"]'),
    toolbar.querySelector('[onclick="openCameraPopout()"]'),
    $("resolutionBadge"),
    document.querySelector(".ui4-app-health"),
    document.querySelector(".system-status-strip"),
  ].filter(Boolean);
  lowFrequency.forEach(node=>healthPopover.appendChild(node));
  document.querySelector(".ui4-command-bar")?.appendChild(healthPopover);
  arrangeCameraToolbar();
  window.addEventListener("resize",arrangeCameraToolbar,{passive:true});

  const primaryTabs=inspector.querySelector(".ui4-inspector-primary-tabs");
  const currentView=document.createElement("div");
  currentView.className="ui4-current-card-view";
  const recentView=document.createElement("div");
  recentView.className="ui4-recent-scans-view";
  recentView.hidden=true;
  [...inspector.children].forEach(child=>{
    if(child!==primaryTabs&&!child.classList.contains("inspector-head")) currentView.appendChild(child);
  });
  const stickyActions=currentView.querySelector(".inspector-actions");
  if(stickyActions) currentView.appendChild(stickyActions);
  inspector.append(currentView,recentView);
  if($("inspectorEmpty")) $("inspectorEmpty").style.display="none";
  if($("inspectorMain")) $("inspectorMain").style.display="grid";
  primaryTabs?.querySelectorAll("[data-inspector-view]").forEach(button=>{
    button.addEventListener("click",()=>setUI4InspectorView(button.dataset.inspectorView));
  });

  const widgetWorkspace=$("widgetWorkspace");
  if(widgetWorkspace){
    widgetWorkspace.addEventListener("click",event=>{
      const actionButton=event.target.closest("[data-widget-action]");
      const widget=event.target.closest("[data-studiox-widget]");
      if(actionButton&&widget){
        updateStudioXWidgetLayout(
          widget.dataset.studioxWidget,
          actionButton.dataset.widgetAction
        );
        return;
      }
      const focusButton=event.target.closest("[data-widget-focus]");
      if(focusButton){
        setPremiumIntelligenceTab(focusButton.dataset.widgetFocus);
      }
    });
  }
  document.querySelectorAll("[data-widget-visibility]").forEach(input=>{
    input.addEventListener("change",()=>{
      updateStudioXWidgetLayout(
        input.dataset.widgetVisibility,
        "visibility",
        input.checked
      );
    });
  });
  document.querySelector("[data-widget-reset]")?.addEventListener(
    "click",
    resetStudioXWidgetLayout
  );
  studioXPreferences=loadStudioXPreferences();
  secondaryBayPreferences=loadSecondaryBayPreferences();
  cameraWorkspacePreferences=loadCameraWorkspacePreferences();
  applyWorkspaceLayoutPreset(
    studioXPreferences.layoutPreset,
    {persist:false}
  );
  $("workspaceLayoutPreset")?.addEventListener("change",event=>{
    applyWorkspaceLayoutPreset(event.target.value);
  });
  $("viewerModeSelect")?.addEventListener("change",event=>{
    setStudioXViewerMode(event.target.value);
  });
  $("viewerZoomOut")?.addEventListener("click",()=>{
    adjustStudioXPreviewZoom(-.1);
  });
  $("viewerZoomReset")?.addEventListener("click",resetStudioXPreviewZoom);
  $("viewerZoomIn")?.addEventListener("click",()=>{
    adjustStudioXPreviewZoom(.1);
  });
  $("secondaryBayMode")?.addEventListener("change",event=>setSecondaryBayMode(event.target.value));
  $("secondaryBaySize")?.addEventListener("change",event=>{
    secondaryBayPreferences=normalizeSecondaryBayPreferences({...secondaryBayPreferences,size:event.target.value});
    saveSecondaryBayPreferences();
    renderSecondaryWorkspaceBay();
  });
  $("cameraSlot1Source")?.addEventListener("change",event=>setActiveCameraWorkspaceSource(event.target.value));
  $("stagingSourceSelect")?.addEventListener("change",event=>setCameraWorkspaceSource(2,event.target.value));
  $("swapSourcesButton")?.addEventListener("click",promoteSecondaryStagingSource);
  $("promoteStagingButton")?.addEventListener("click",()=>promoteCameraWorkspaceSlot(2));
  $("collapseSecondaryBay")?.addEventListener("click",()=>setSecondaryBayMode("hidden"));
  $("cameraWorkspaceLayout")?.addEventListener("click",event=>{
    const button=event.target.closest("[data-camera-layout-option]");
    if(button) setCameraWorkspaceLayout(button.dataset.cameraLayoutOption);
  });
  $("manageCamerasButton")?.addEventListener("click",()=>{
    const actions=document.querySelector(".camera-source-compact-menu");
    actions?.focus();
    actions?.scrollIntoView({block:"nearest",inline:"nearest"});
  });
  $("cameraSlot1Side")?.addEventListener("change",event=>setCameraWorkspaceSide(1,event.target.value));
  $("cameraSlot2Side")?.addEventListener("change",event=>setCameraWorkspaceSide(2,event.target.value));
  [3,4].forEach(slot=>{
    $(`cameraSlot${slot}Source`)?.addEventListener("change",event=>setCameraWorkspaceSource(slot,event.target.value));
    $(`cameraSlot${slot}Side`)?.addEventListener("change",event=>setCameraWorkspaceSide(slot,event.target.value));
    $(`promoteCameraSlot${slot}`)?.addEventListener("click",()=>promoteCameraWorkspaceSlot(slot));
  });
  if(secondaryBayPreferences.activeSource&&$("cameraSelect")){
    const savedActive=secondaryBayPreferences.activeSource;
    if([...$("cameraSelect").options].some(option=>option.value===savedActive)){
      $("cameraSelect").value=savedActive;
    }
  }
  renderSecondaryWorkspaceBay();
  cameraWorkspacePreferences.sources["1"]=$("cameraSelect")?.value||cameraWorkspacePreferences.sources["1"];
  cameraWorkspacePreferences.sources["2"]=secondaryBayPreferences.stagingSource||cameraWorkspacePreferences.sources["2"];
  saveCameraWorkspacePreferences();
  renderCameraWorkspace();
  studioXWidgetLayout=loadStudioXWidgetLayout();
  applyStudioXWidgetLayout();
  updateSharedCardContext(
    deriveSharedCardContext(
      deriveRecognitionPresentation({phase:"IDLE"},null,[]),
      null,
      {phase:"IDLE"},
      []
    )
  );

  const actions=document.querySelector(".inspector-actions");
  const reaction=actions?[...actions.querySelectorAll("button")].find(
    button=>["Reaction","Next Card","Next / Clear"].includes(button.textContent.trim())
  ):null;
  if(reaction){
    reaction.textContent="Next / Clear";
    reaction.addEventListener("click",()=>resetRecognitionPresentation("operator_clear"));
  }
  setPremiumIntelligenceTab("identify");
  setUI4InspectorView("current",false);
  setUI4DiagnosticsOpen(false);
  setUI4HealthOpen(false);
  switchWorkspace("live");
}


document.addEventListener("DOMContentLoaded",()=>{
  initializeAutoScreenshotConfiguration();
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
          $("cameraRecoveryTitle").textContent="Recovering live preview...";
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
    renderSecondaryWorkspaceBay();
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


/* =========================================================
   RareIQ UI 4.0 card intelligence normalization
   Frontend placeholders only. Missing values remain null.
   ========================================================= */

function firstCardValue(source,keys){
  for(const key of keys){
    const value=source?.[key];
    if(value!==undefined&&value!==null&&value!=="") return value;
  }
  return null;
}

function nullableCardNumber(value){
  if(value===undefined||value===null||value==="") return null;
  const number=Number(value);
  return Number.isFinite(number)&&number>0?number:null;
}

function cardMoney(value){
  const number=nullableCardNumber(value);
  return number===null
    ? "No public data"
    : new Intl.NumberFormat("en-US",{
        style:"currency",
        currency:"USD",
        minimumFractionDigits:2,
        maximumFractionDigits:2
      }).format(number);
}

function cardText(value,fallback="--"){
  const text=String(value??"").trim();
  return text||fallback;
}

function setCardText(id,value,fallback="--"){
  const node=$(id);
  if(node) node.textContent=cardText(value,fallback);
}

function normalizeCardPricing(card={}){
  const pricing=card.pricing||{};
  const prices=card.prices||{};
  const market=pricing.market||pricing.market_price||prices.market||prices.raw||null;

  return {
    currency:firstCardValue(pricing,["currency","unit"])||"USD",
    rawMarket:firstCardValue(card,[
      "market_price","raw_market","raw_value","price"
    ])??market,
    rawLow:firstCardValue(card,[
      "raw_low","low_price","market_low"
    ])??firstCardValue(pricing,["low","low_price"]),
    rawHigh:firstCardValue(card,[
      "raw_high","high_price","market_high"
    ])??firstCardValue(pricing,["high","high_price"]),
    psa10:firstCardValue(card,[
      "psa10_price","psa_10_price","graded_10_value"
    ])??firstCardValue(pricing,["psa10","psa_10"]),
    psa9:firstCardValue(card,[
      "psa9_price","psa_9_price","graded_9_value"
    ])??firstCardValue(pricing,["psa9","psa_9"]),
    psa8:firstCardValue(card,[
      "psa8_price","psa_8_price","graded_8_value"
    ])??firstCardValue(pricing,["psa8","psa_8"]),
    lastSoldRaw:firstCardValue(card,[
      "last_sold_raw","raw_last_sold"
    ])??firstCardValue(pricing,["last_sold_raw"]),
    lastSoldPsa10:firstCardValue(card,[
      "last_sold_psa10","psa10_last_sold"
    ])??firstCardValue(pricing,["last_sold_psa10"]),
    population:firstCardValue(card,[
      "population","psa10_population","psa_10_population"
    ]),
    salesVolume30d:firstCardValue(card,[
      "sales_volume_30d","sales_30d","volume_30d"
    ])??firstCardValue(pricing,["sales_volume_30d"]),
    provider:firstCardValue(card,[
      "price_source","pricing_source"
    ])??firstCardValue(pricing,["source","provider"]),
    updatedAt:firstCardValue(card,[
      "price_updated_at","pricing_updated_at"
    ])??firstCardValue(pricing,["updated_at","updatedAt"])
  };
}

function deriveMarketPresentation(card={},pricing=normalizeCardPricing(card)){
  const providerError=Boolean(
    card?.pricing_error||
    card?.provider_error||
    pricing?.status==="error"
  );
  const pending=Boolean(
    card?.pricing_pending||
    pricing?.status==="pending"
  );
  const hasValue=[
    pricing.rawMarket,pricing.rawLow,pricing.rawHigh,
    pricing.psa10,pricing.psa9,pricing.psa8
  ].some(value=>nullableCardNumber(value)!==null);
  if(providerError) return {key:"provider-error",label:"Provider unavailable"};
  if(pending) return {key:"pending",label:"Fetching market data"};
  if(hasValue) return {key:"available",label:cardMoney(pricing.rawMarket)};
  return {key:"no-data",label:"No public market data"};
}

function rarityEventTier(card={}){
  const rarity=String(
    card.rarity_tier||
    card.rarity||
    ""
  ).toLowerCase();

  if(
    rarity.includes("special art")||
    rarity.includes("special illustration")||
    rarity.includes("sar")||
    rarity.includes("secret")
  ) return "Special";

  if(
    rarity.includes("illustration")||
    rarity.includes("art rare")||
    rarity.includes("ir")
  ) return "Illustration Rare";

  if(
    rarity.includes("double rare")||
    rarity.includes("double")||
    rarity.includes("ex")
  ) return "Double Rare";

  if(rarity.includes("rare")) return "Rare";
  return "Standard";
}

function rarityAnimationName(tier){
  return {
    "Special":"Cinematic chase reveal",
    "Illustration Rare":"Illustration shimmer",
    "Double Rare":"Double Rare burst",
    "Rare":"Rare shimmer",
    "Standard":"Standard reveal"
  }[tier]||"Standard reveal";
}

function raritySoundName(tier){
  return {
    "Special":"Special card fanfare",
    "Illustration Rare":"Illustration Rare hit",
    "Double Rare":"Double Rare hit",
    "Rare":"Rare hit",
    "Standard":"Default scan"
  }[tier]||"Default scan";
}

function readablePriceTimestamp(value){
  if(!value) return "--";
  const numeric=Number(value);
  const date=Number.isFinite(numeric)
    ? new Date(numeric<100000000000?numeric*1000:numeric)
    : new Date(value);
  return Number.isNaN(date.getTime())
    ? "--"
    : date.toLocaleString();
}

function syncCardMetadataVisibility(){
  [
    "cardSetName","cardSetCode","cardCollectorNumber","cardOfficialNumber",
    "cardLanguage","cardRarity","cardVariant","cardFinish","cardReleaseYear",
  ].forEach(id=>{
    const value=$(id);
    const field=value?.closest(".ui4-identity-grid>div");
    if(!value||!field) return;
    const text=String(value.textContent||"").trim().toLowerCase();
    field.hidden=!text||text==="--"||text==="null"||text==="undefined";
  });
}

function renderExtendedCardData(card={},snapshot={},confidence=0,verified=false){
  const printedName=firstCardValue(card,[
    "printed_name","localized_name","name"
  ]);
  const englishName=firstCardValue(card,[
    "english_name","translated_name","canonical_name"
  ]);
  const pricing=normalizeCardPricing(card);
  const marketPresentation=deriveMarketPresentation(card,pricing);
  const tier=rarityEventTier(card);

  setCardText("cardPrintedName",printedName);
  setCardText("cardEnglishName",englishName);
  setCardText("cardPokemonName",firstCardValue(card,[
    "pokemon_name","character_name","species"
  ])||englishName||printedName);

  setCardText("cardSetName",firstCardValue(card,[
    "set_name","set"
  ]));
  setCardText("cardSetCode",firstCardValue(card,[
    "set_code","set_id"
  ]));
  setCardText("cardCollectorNumber",firstCardValue(card,[
    "collector_number","card_number"
  ])||snapshot?.collector_number);
  const officialNumber=firstCardValue(card,[
    "official_collector_number"
  ])||snapshot?.official_collector_number;
  setCardText("cardOfficialNumber",officialNumber);
  const officialField=$("officialNumberField");
  if(officialField) officialField.hidden=!officialNumber;
  setCardText("cardLanguage",firstCardValue(card,[
    "language","language_name","language_code"
  ])||snapshot?.language);
  setCardText("cardRarity",card.rarity);
  setCardText("cardVariant",firstCardValue(card,[
    "variant","variant_name","rarity_variant"
  ]));
  setCardText("cardFinish",firstCardValue(card,[
    "finish","foil","foil_type","surface"
  ]));
  setCardText("cardReleaseYear",firstCardValue(card,[
    "release_year","year"
  ]));
  setCardText("cardTypeValue",firstCardValue(card,[
    "card_type","category","supertype"
  ]));
  setCardText("cardHpValue",firstCardValue(card,["hp"]));
  setCardText("cardEnergyType",firstCardValue(card,[
    "energy_type","type","types"
  ]));

  setCardText("rawValue",cardMoney(pricing.rawMarket));
  setCardText("rawLowValue",cardMoney(pricing.rawLow));
  setCardText("rawHighValue",cardMoney(pricing.rawHigh));
  setCardText("psaValue",cardMoney(pricing.psa10));
  setCardText("psa9Value",cardMoney(pricing.psa9));
  setCardText("psa8Value",cardMoney(pricing.psa8));
  setCardText("lastSoldRawValue",cardMoney(pricing.lastSoldRaw));
  setCardText("lastSoldPsa10Value",cardMoney(pricing.lastSoldPsa10));
  setCardText("populationValue",pricing.population);
  setCardText("salesVolumeValue",pricing.salesVolume30d);
  setCardText("pricingSource",pricing.provider,"No provider connected");
  setCardText("pricingUpdatedAt",readablePriceTimestamp(pricing.updatedAt));
  const priceSummary=document.querySelector(".ui4-price-summary");
  if(priceSummary) priceSummary.dataset.marketState=marketPresentation.key;
  setCardText("cardValue",marketPresentation.label);

  setCardText("rarityTierValue",tier);
  setCardText("overlayAnimationValue",rarityAnimationName(tier));
  setCardText("overlaySoundValue",raritySoundName(tier));
  setCardText(
    "overlayTrackingValue",
    verified
      ? "Locked to recognized card"
      : confidence>=0.68
      ? "Candidate tracking"
      : "Waiting for lock"
  );
  syncCardMetadataVisibility();
}

function resetExtendedCardData(){
  [
    "cardPrintedName",
    "cardEnglishName",
    "cardPokemonName",
    "cardSetName",
    "cardSetCode",
    "cardCollectorNumber",
    "cardLanguage",
    "cardRarity",
    "cardVariant",
    "cardFinish",
    "cardReleaseYear",
    "cardTypeValue",
    "cardHpValue",
    "cardEnergyType",
    "rawLowValue",
    "rawHighValue",
    "psa9Value",
    "psa8Value",
    "lastSoldRawValue",
    "lastSoldPsa10Value",
    "salesVolumeValue",
    "pricingUpdatedAt"
  ].forEach(id=>setCardText(id,null));

  setCardText("rawValue",null,"No public data");
  setCardText("psaValue",null,"No public data");
  setCardText("populationValue",null);
  setCardText("pricingSource",null,"No provider connected");
  const officialField=$("officialNumberField");
  if(officialField) officialField.hidden=true;
  syncCardMetadataVisibility();
  const priceSummary=document.querySelector(".ui4-price-summary");
  if(priceSummary) priceSummary.dataset.marketState="pending";
  setCardText("rarityTierValue","Standard");
  setCardText("overlayAnimationValue","Standard reveal");
  setCardText("overlaySoundValue","Default scan");
  setCardText("overlayTrackingValue","Waiting for lock");
}







