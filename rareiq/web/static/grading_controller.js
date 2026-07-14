/*
 * GradingController
 * Owns CardGrader connection, captures and scan polling.
 */
function renderCardGraderStatus(payload) {
  const data = payload?.cardgrader || payload || {};
  $("gradeCredits").textContent = String(data.agent?.creditsRemaining ?? data.agent?.credits ?? "—");
}

async function refreshCardGraderStatus() {
  const result = await fetch("/api/cardgrader/status", {cache:"no-store"}).then(r => r.json());
  renderCardGraderStatus(result);
}

async function registerCardGrader() {
  const result = await post("/api/cardgrader/register", {
    name:$("gradeAgentName").value.trim() || "RareIQ",
    contact_email:$("gradeContactEmail").value.trim() || null
  });
  $("gradeResult").textContent = result.ok ? "API registered and saved locally." : result.error || "Registration failed.";
  await refreshCardGraderStatus();
}

async function saveCardGraderKey() {
  const result = await post("/api/cardgrader/key", {api_key:$("gradeApiKey").value.trim()});
  $("gradeResult").textContent = result.ok ? "API key saved and verified." : result.error || "Key failed.";
  if (result.ok) $("gradeApiKey").value = "";
  await refreshCardGraderStatus();
}

async function captureGradeFront() {
  const result = await post("/api/cardgrader/capture-front");
  $("gradeResult").textContent = result.ok ? `Front captured: ${result.path}` : result.error;
}

async function captureGradeBack() {
  const result = await post("/api/cardgrader/capture-back");
  $("gradeResult").textContent = result.ok ? `Back captured: ${result.path}` : result.error;
}

async function submitGradeScan() {
  $("gradeStatus").textContent = "Submitting";
  const result = await post("/api/cardgrader/submit", {
    module:$("gradeModule").value,
    include_back:$("gradeIncludeBack").checked
  });
  if (!result.ok) {
    $("gradeStatus").textContent = "Error";
    $("gradeResult").textContent = result.error || "Submit failed.";
    return;
  }
  activeGradeScanId = result.scan?.id;
  $("gradeStatus").textContent = result.scan?.status || "Queued";
  $("gradeResult").textContent = `Scan ${activeGradeScanId} submitted.`;
  if (gradePollTimer) clearInterval(gradePollTimer);
  gradePollTimer = setInterval(pollGradeScan, 3000);
  pollGradeScan();
}

async function pollGradeScan() {
  if (!activeGradeScanId) return;
  const result = await fetch(`/api/cardgrader/scan/${activeGradeScanId}`, {cache:"no-store"}).then(r => r.json());
  if (!result.ok) {
    clearInterval(gradePollTimer);
    gradePollTimer = null;
    $("gradeStatus").textContent = "Error";
    $("gradeResult").textContent = result.error || "Polling failed.";
    return;
  }
  const scan = result.scan || {};
  $("gradeStatus").textContent = scan.status || "Processing";
  $("gradeProgress").textContent = scan.progressPercent != null ? `${scan.progressPercent}%` : "—";
  if (scan.status === "completed") {
    clearInterval(gradePollTimer);
    gradePollTimer = null;
    const grading = scan.grading || {};
    $("gradePredicted").textContent = String(grading.predictedGrade ?? grading.grade ?? "—");
    $("gradeResult").textContent = JSON.stringify(scan, null, 2);
    await refreshCardGraderStatus();
  }
}

window.GradingController = Object.freeze({
  refresh: refreshCardGraderStatus,
  register: registerCardGrader,
  saveKey: saveCardGraderKey,
  captureFront: captureGradeFront,
  captureBack: captureGradeBack,
  submit: submitGradeScan,
});
