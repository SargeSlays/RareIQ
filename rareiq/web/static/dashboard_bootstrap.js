/*
 * RareIQ dashboard bootstrap.
 * This file contains wiring only; feature logic lives in dedicated controllers.
 */
connectRareIQ(message => {
  if(message.type === "snapshot"){
    if(message.payload?.session) renderSession(message.payload.session);
    if(message.payload?.recognition_state){
      renderUnifiedRecognition(message.payload.recognition_state);
    }
    return;
  }

  if(message.type === "recognition_state_update"){
    renderUnifiedRecognition(message.payload || {});
    return;
  }

  if(message.type === "session_update"){
    renderSession(message.payload || {});
  }
});

setInterval(() => $("clock").textContent = new Date().toLocaleTimeString(), 1000);
initializeCameraFeedRecovery();
loadCameras();
loadSets();
loadMasterCatalogStatus();
loadPokemonMasterStatus();
loadPokemonVisionStatus();
loadStorageStatus();
loadMasterBuilderStatus();
loadProviderStatus();
loadFastPipelineStatus();
loadWarRoomStatus();
loadIndexActivationStatus();
loadSystemHealth();
loadIntelligenceStatus();
refreshCardGraderStatus();
$("autoAddVerified").checked = localStorage.getItem("rareiq-auto-add") === "1";
$("autoAddTestMode").checked = localStorage.getItem("rareiq-auto-add-test") === "1";
if($("autoAddTestMode").checked){
  $("autoAddLatchStatus").textContent = "TEST MODE — unverified candidates may be added";
}
refreshSessionWorkflow();
let unifiedPollBusy = false;
async function pollImmutableRecognition(){
  if(unifiedPollBusy) return;
  unifiedPollBusy = true;
  try{
    const response = await fetch("/api/recognition-state", {cache:"no-store"});
    const data = await response.json();
    const snapshot = data.recognition_state || {};
    const currentId = state.recognitionState?.state_id;
    if(snapshot.state_id && snapshot.state_id !== currentId){
      renderUnifiedRecognition(snapshot);
    }
  }catch(error){
    const diagnostic = $("autoAddDiagnostic");
    if(diagnostic) diagnostic.textContent = "Immutable state connection interrupted.";
  }finally{
    unifiedPollBusy = false;
  }
}
pollImmutableRecognition();
setInterval(pollImmutableRecognition, 1500);

let cameraStatusPollBusy = false;
async function pollCameraStatus(){
  if(cameraStatusPollBusy) return;
  cameraStatusPollBusy = true;

  try{
    const response = await fetch("/api/camera/status", {cache:"no-store"});
    const data = await response.json();
    renderVision(data.vision || data || {});
  }catch(error){
    // The recognition UI remains usable while camera recovery retries.
  }finally{
    cameraStatusPollBusy = false;
  }
}

pollCameraStatus();
setInterval(pollCameraStatus, 2500);
setInterval(loadMasterCatalogStatus, 10000);
setInterval(loadPokemonMasterStatus, 2000);
setInterval(loadPokemonVisionStatus, 2000);
setInterval(loadStorageStatus, 15000);
setInterval(loadMasterBuilderStatus, 1000);
setInterval(loadProviderStatus, 30000);
setInterval(loadFastPipelineStatus, 1000);
setInterval(loadWarRoomStatus, 3000);
setInterval(loadIndexActivationStatus, 1000);
setInterval(loadSystemHealth, 2000);
setInterval(loadIntelligenceStatus, 3000);
