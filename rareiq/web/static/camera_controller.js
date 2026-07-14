/*
 * CameraController
 * Owns only the camera device, MJPEG stream, reconnect lifecycle and captures.
 * Recognition state is never allowed to attach, detach or replace the feed.
 */
let cameraStreamAttached = false;
let cameraStreamRetryTimer = null;
let cameraStreamLastAttach = 0;

function cameraStreamUrl(){
  return `/api/camera/stream?t=${Date.now()}`;
}

function attachCameraStream(force=false){
  const feed = $("cameraFeed");
  if(!feed) return;

  const hasSource = Boolean(feed.getAttribute("src"));

  // An MJPEG request is intentionally endless, so its normal image "load"
  // event is not a reliable attachment signal. If a source already exists,
  // leave it alone unless the operator explicitly requests a reconnect.
  if(!force && hasSource){
    cameraStreamAttached = true;
    return;
  }

  cameraStreamLastAttach = Date.now();
  cameraStreamAttached = true;
  feed.src = cameraStreamUrl();
}

function detachCameraStream(){
  const feed = $("cameraFeed");
  if(!feed) return;

  cameraStreamAttached = false;
  feed.removeAttribute("src");

  if(cameraStreamRetryTimer){
    clearTimeout(cameraStreamRetryTimer);
    cameraStreamRetryTimer = null;
  }
}

function scheduleCameraStreamRetry(){
  if(cameraStreamRetryTimer) return;

  cameraStreamRetryTimer = setTimeout(() => {
    cameraStreamRetryTimer = null;

    const running = Boolean(
      state.vision?.running ||
      state.recognitionState?.vision?.running
    );

    if(running){
      attachCameraStream(true);
    }
  }, 1200);
}

function initializeCameraFeedRecovery(){
  const feed = $("cameraFeed");
  if(!feed || feed.dataset.recoveryReady === "1") return;

  feed.dataset.recoveryReady = "1";
  cameraStreamAttached = Boolean(feed.getAttribute("src"));

  feed.addEventListener("load", () => {
    cameraStreamAttached = true;
    if(cameraStreamRetryTimer){
      clearTimeout(cameraStreamRetryTimer);
      cameraStreamRetryTimer = null;
    }
  });

  feed.addEventListener("error", () => {
    // Do not restart an MJPEG request automatically. Chrome may briefly emit
    // an image error while the multipart connection remains recoverable.
    // Automatic retries caused the visible once-per-second flash.
    cameraStreamAttached = Boolean(feed.getAttribute("src"));
  });
}

function renderVision(v) {
  state.vision = v || {};
  const running = Boolean(v?.running);

  $("kpiCamera").textContent = running ? "Live" : "Offline";
  $("kpiCameraSub").textContent = v?.camera_name || "No device";

  const badge = $("cameraBadge");
  const label = badge.querySelector("b");
  const visionText = !running
    ? "OFFLINE"
    : v?.stable
      ? "LOCKING"
      : v?.visible
        ? "OCR ACTIVE"
        : "SEARCHING";

  label.textContent = visionText;
  badge.dataset.state = !running ? "offline" : "active";
  $("cameraEmpty").style.display = running ? "none" : "grid";

  // Camera status only updates labels. It never restarts or detaches the
  // MJPEG transport. Start, Stop and Reconnect own the stream lifecycle.
}

async function loadCameras() {
  const result = await fetch("/api/cameras", {cache:"no-store"}).then(r => r.json());
  const select = $("cameraSelect");
  select.innerHTML = "";
  (result.cameras || []).forEach(camera => {
    const option = document.createElement("option");
    option.value = JSON.stringify({camera_index:camera.index,camera_backend:camera.backend});
    option.textContent = `${camera.name} (#${camera.index})`;
    select.appendChild(option);
  });
  if (!select.options.length) select.innerHTML = "<option>No cameras found</option>";
}

async function startCamera() {
  if (!$("cameraSelect").value || !$("cameraSelect").value.startsWith("{")) return;

  const payload = JSON.parse($("cameraSelect").value);
  const result = await post("/api/camera/start", payload);

  if(result.ok){
    renderVision(result.vision || {running:true});
    attachCameraStream(true);
  }
}

async function stopCamera() {
  const result = await post("/api/camera/stop");
  detachCameraStream();
  renderVision(result.vision || {});
}

async function captureCard() {
  const result = await post("/api/camera/capture");
  $("developerStatus").textContent = result.ok ? `Captured: ${result.path || "saved"}` : result.error || "Capture failed.";
}

async function toggleAutoCapture() {
  await post("/api/camera/auto-capture", {enabled:$("autoCapture").checked});
}

window.CameraController = Object.freeze({
  load: loadCameras,
  start: startCamera,
  stop: stopCamera,
  capture: captureCard,
  reconnect: () => attachCameraStream(true),
  render: renderVision,
  initialize: initializeCameraFeedRecovery,
});
