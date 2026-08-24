const $ = id => document.getElementById(id);
const state = {vision:{}, recognition:{}, recognitionState:{}, session:{}, catalog:{}, sets:{}};
let activeGradeScanId = null;
let gradePollTimer = null;
let wasRecognitionLocked = false;
let lastLockAt = 0;
let lastAutoAddedSignature = "";
let autoAddInFlight = false;
let autoAddArmed = true;
let lastAutoAttemptAt = 0;
let autoReadySince = null;
const AUTO_ADD_ATTEMPT_COOLDOWN_MS = 3500;
const AUTO_ADD_STABLE_MS = 900;

async function post(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: body ? {"Content-Type":"application/json"} : undefined,
    body: body ? JSON.stringify(body) : undefined
  });
  return response.json();
}

function focusPanel(id) {
  const panel = $(id);
  if (!panel) return;
  panel.animate(
    [{boxShadow:"0 0 0 rgba(86,216,255,0)"},{boxShadow:"0 0 34px rgba(86,216,255,.45)"},{boxShadow:"0 14px 36px rgba(0,0,0,.26)"}],
    {duration:650}
  );
}

function showTool(name) {
  document.querySelectorAll(".tool-view").forEach(el => el.classList.remove("active"));
  document.querySelectorAll(".tabs button").forEach(el => el.classList.remove("active"));
  $(`tool-${name}`)?.classList.add("active");
  $(`tab-${name}`)?.classList.add("active");
}

function openDrawer() { $("gradeDrawer").classList.add("open"); }
function closeDrawer() { $("gradeDrawer").classList.remove("open"); }
