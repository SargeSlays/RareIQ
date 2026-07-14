/*
 * RecognitionController
 * Renders one immutable RecognitionSnapshot. It does not own camera transport,
 * batch mutations or catalog importing.
 */
function renderActiveSet(setInfo, indexStatus) {
  const active = setInfo || {};
  state.sets.active = active;
  $("kpiSet").textContent = active.name || "All References";
  $("kpiSetSub").textContent = `${active.language || "Any"} • ${active.game || "Any"}`;
  $("kpiIndexed").textContent = String(indexStatus?.record_count || 0);
  $("devIndex").textContent = String(indexStatus?.record_count || 0);
  $("setStatus").textContent = active.name
    ? `Active: ${active.game || "Any"} • ${active.language || "Any"} • ${active.name}`
    : "Choose the product currently being opened.";
}


function mergedCandidates(r){
  return Array.isArray(r?.candidates) ? r.candidates : [];
}

function topCandidate(r) {
  return r?.primary_candidate || (Array.isArray(r?.candidates) ? r.candidates[0] : null) || null;
}

function renderTimeline(r) {
  const stages = r?.pipeline_stages || [];
  const keys = ["detect","ocr","fingerprint","candidates","verify"];
  const labels = ["DETECT","OCR","ARTWORK","CATALOG","VERIFY"];
  const root = $("timeline");
  root.innerHTML = "";
  keys.forEach((key, index) => {
    const source = stages.find(s => s.key === key) ||
      (key === "candidates" ? stages.find(s => s.key === "index") : null);
    const el = document.createElement("div");
    const firstPending = keys.findIndex(testKey => {
      const testSource = stages.find(s => s.key === testKey) ||
        (testKey === "candidates" ? stages.find(s => s.key === "index") : null);
      return testSource?.state !== "done";
    });
    const isCurrent = index === firstPending && firstPending >= 0;
    el.className = "stage" + (source?.state === "done" ? " done" : "") + (isCurrent ? " current" : "");
    el.innerHTML = `<i></i><span>${labels[index][0] + labels[index].slice(1).toLowerCase()}</span>`;
    root.appendChild(el);
  });

  const done = key => stages.some(s => s.key === key && s.state === "done");
  $("checkDetect").textContent = done("detect") ? "✓" : "○";
  $("checkOcr").textContent = done("ocr") ? "✓" : "○";
  $("checkArt").textContent = done("fingerprint") ? "✓" : "○";
  $("checkCandidate").textContent = (done("candidates") || done("index")) ? "✓" : "○";
  $("checkVerify").textContent = done("verify") ? "✓" : "○";
}

function renderCandidates(r) {
  const candidates = (Array.isArray(r?.candidates) ? r.candidates : []).slice(0,5);
  const list = $("candidateList");
  list.innerHTML = "";

  if(!candidates.length){
    list.innerHTML = `
      <div class="candidate waiting-row">
        <div class="rank">—</div>
        <div class="candidate-thumb placeholder">CARD</div>
        <div>
          <div class="candidate-name">Waiting for recognition</div>
          <div class="candidate-sub">Candidates will update live.</div>
        </div>
        <div class="score">—</div>
      </div>`;
    return;
  }

  candidates.forEach((candidate,index)=>{
    const row = document.createElement("div");
    row.className = "candidate" + (index === 0 ? " best" : "");
    const score = Math.round(Number(candidate.fused_score ?? candidate.score ?? 0) * 100);
    const official = bestOfficialImage(r,candidate);
    const thumb = official
      ? `<img class="candidate-thumb" src="${official}" alt="">`
      : `<img class="candidate-thumb live-fallback" src="/api/camera/crop.jpg?t=${Date.now()}" alt="">`;
    const english = englishCatalogName(r,candidate);
    row.innerHTML = `
      <div class="rank">${index + 1}</div>
      ${thumb}
      <div class="candidate-copy">
        <div class="candidate-name">${english || candidate.name || candidate.printed_name || "Unknown card"}</div>
        ${english && (candidate.printed_name || r?.name_candidate)
          ? `<div class="candidate-printed">${candidate.printed_name || r?.name_candidate}</div>`
          : ""}
        <div class="candidate-sub">${candidate.collector_number || r?.collector_number || "—"} • ${candidate.language || r?.language || "Unknown"} • ${candidate.provisional ? "PROVISIONAL OCR" : candidate.set_name || candidate.source || "local"}</div>
        <div class="candidate-bar"><i style="width:${Math.max(0,Math.min(100,score))}%"></i></div>
      </div>
      <div class="score">${score}%</div>`;
    list.appendChild(row);
  });
}

function animateConfidence(target){
  const ring = $("confidenceRing");
  const label = $("confidencePct");
  const current = Number(ring.dataset.value || 0);
  const start = performance.now();
  const duration = 420;
  const tick = now => {
    const p = Math.min(1,(now-start)/duration);
    const value = Math.round(current + (target-current)*p);
    ring.style.setProperty("--p", value);
    ring.dataset.value = String(value);
    label.textContent = `${value}%`;
    if(p<1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}


function setBreakdown(id, value){
  const row = $(id);
  const numeric = Number(value);
  if(!Number.isFinite(numeric) || numeric <= 0){
    row.classList.add("hidden");
    return;
  }
  const pct = Math.max(0,Math.min(100,Math.round(numeric)));
  row.classList.remove("hidden");
  row.querySelector("i").style.width = `${pct}%`;
  row.querySelector("b").textContent = `${pct}%`;
}

function setLatencyClass(value){
  const el = $("kpiLatency");
  el.classList.remove("latency-good","latency-warn","latency-bad");
  if(!Number.isFinite(value)) return;
  el.classList.add(value < 800 ? "latency-good" : value <= 1500 ? "latency-warn" : "latency-bad");
}

function toggleDeveloperMode(){
  document.body.classList.toggle("developer-mode",$("developerModeToggle").checked);
  if(!$("developerModeToggle").checked && $("tool-developer").classList.contains("active")){
    showTool("catalog");
  }
}

function showMatchLock(r,candidate,overall){
  const now = Date.now();
  if(now-lastLockAt < 2200) return;
  lastLockAt = now;
  const overlay = $("matchLockOverlay");
  const canvas = $("lockCanvas");
  const source = $("cameraFeed");
  const ctx = canvas.getContext("2d");
  canvas.width = Math.max(640,source.naturalWidth || 640);
  canvas.height = Math.max(420,source.naturalHeight || 420);
  try{
    ctx.drawImage(source,0,0,canvas.width,canvas.height);
  }catch(error){
    ctx.fillStyle="#02070d";
    ctx.fillRect(0,0,canvas.width,canvas.height);
  }
  $("lockName").textContent = candidate?.name || candidate?.printed_name || r?.name_candidate || "Card Locked";
  $("lockMeta").textContent = [candidate?.collector_number || r?.collector_number,candidate?.language || r?.language].filter(Boolean).join(" • ") || "Verified candidate";
  $("lockConfidence").textContent = `${overall}%`;
  overlay.classList.remove("show");
  overlay.setAttribute("aria-hidden","false");
  void overlay.offsetWidth;
  overlay.classList.add("show");
  setTimeout(()=>{
    overlay.classList.remove("show");
    overlay.setAttribute("aria-hidden","true");
  },980);
}


function normalizedImageUrl(value){
  if(!value) return null;
  const raw = String(value).trim().replace(/\/+$/,"");
  if(/\.(png|jpe?g|webp)(\?.*)?$/i.test(raw)) return raw;
  return `${raw}/high.webp`;
}

function catalogCandidates(){
  return state.catalog?.candidates || [];
}

function matchCatalogCard(r,candidate){
  const match = state.catalog?.match;
  if(match) return match;
  const wanted = String(candidate?.collector_number || r?.collector_number || "")
    .replace(/^0+/,"");
  return catalogCandidates().find(card =>
    String(card.collector_number || "").replace(/^0+/,"") === wanted
  ) || catalogCandidates()[0] || null;
}

function englishCatalogName(r,candidate){
  const catalogCard = matchCatalogCard(r,candidate);
  if(!catalogCard) return null;
  if(catalogCard.english_name) return catalogCard.english_name;
  if(catalogCard.language_code === "en") return catalogCard.name || null;
  const englishPartner = catalogCandidates().find(card =>
    card.language_code === "en" &&
    card.collector_number === catalogCard.collector_number
  );
  return englishPartner?.name || null;
}

function bestOfficialImage(r,candidate){
  const catalogCard = matchCatalogCard(r,candidate);
  return normalizedImageUrl(
    candidate?.reference_image_url ||
    candidate?.image_url ||
    candidate?.card_image_url ||
    catalogCard?.reference_image_url ||
    catalogCard?.image_url ||
    catalogCard?.image ||
    catalogCard?.english_image_url
  );
}

function renderThinkingFeed(r){
  const root = $("thinkingFeed");
  if(!root) return;
  const candidate = topCandidate(r);
  const stages = r?.pipeline_stages || [];
  const overall = Math.round(Number(r?.overall_confidence || 0) * 100);
  const catalogCard = matchCatalogCard(r,candidate);
  const lines = [];
  const done = key => stages.some(stage => stage.key === key && stage.state === "done");

  lines.push(
    state.vision?.visible || state.vision?.stable
      ? ["done","Card detected inside the scan zone."]
      : ["pending","Searching for a card."]
  );

  if(r?.language) lines.push(["done",`Language identified: ${r.language}.`]);
  else if(!done("ocr")) lines.push(["active","Reading printed text and collector number."]);

  if(r?.collector_number) lines.push(["done",`Collector number: ${r.collector_number}.`]);

  if(candidate){
    const score = Math.round(Number(candidate.fused_score ?? candidate.score ?? 0) * 100);
    lines.push(["done",`Artwork candidate: ${candidate.printed_name || candidate.name || "Unknown"} at ${score}%.`]);
  }else if(!done("fingerprint")){
    lines.push(["active","Comparing artwork fingerprints."]);
  }

  if(state.catalog?.busy){
    lines.push(["active","Searching the live catalog."]);
  }else if(catalogCard){
    const english = englishCatalogName(r,candidate);
    lines.push(["done",english ? `English catalog match: ${english}.` : "Catalog candidate found."]);
  }else if(done("candidates") || done("index")){
    lines.push(["warn","No live catalog match yet; using local visual candidates."]);
  }

  if(r?.recognition_locked) lines.push(["done",`Match verified at ${overall}%.`]);
  else if(r?.provisional_candidate || provisionalCandidate(r)) lines.push(["active",`Provisional OCR candidate available at ${overall}%.`]);
  else if(overall >= 40) lines.push(["active",`Comparing evidence at ${overall}%.`]);

  root.innerHTML = lines.slice(-6).map(([type,text]) =>
    `<div class="thinking-line ${type}"><i></i><span>${text}</span></div>`
  ).join("");
}

function renderCatalogStatus(catalog){
  state.catalog = catalog || {};
}

function applyReferenceImage(candidate){
  const image = $("referenceImage");
  const empty = $("referenceEmpty");
  const src = bestOfficialImage(state.recognition || {}, candidate);
  if(!src){
    image.style.display = "none";
    image.removeAttribute("src");
    empty.style.display = "block";
    empty.textContent = "No official image is available for this candidate yet.";
    return;
  }
  image.onload = () => {
    image.style.display = "block";
    empty.style.display = "none";
  };
  image.onerror = () => {
    image.style.display = "none";
    empty.style.display = "block";
    empty.textContent = "Official image could not be loaded.";
  };
  image.src = `${src}${src.includes("?") ? "&" : "?"}t=${Date.now()}`;
}

function renderUnifiedRecognition(snapshot){
  if(!snapshot || typeof snapshot !== "object") return;

  const current = state.recognitionState;
  if(
    current?.state_id &&
    snapshot?.state_id === current.state_id &&
    snapshot?.revision === current.revision
  ){
    return;
  }

  state.recognitionState = Object.freeze(snapshot);
  state.recognition = state.recognitionState;
  const u = state.recognitionState;

  renderVision(u.vision || {});
  renderRecognition(u);
  renderCandidates(u);
  renderThinkingFeed(u);
  updateProfessionalTelemetry(u);
  maybeAutoAdd(u);

  const readiness = u.auto_add || {};
  const diagnostic = $("autoAddDiagnostic");
  if(diagnostic){
    diagnostic.textContent =
      `State ${u.state_id || "—"} | r${u.revision || 0} | ` +
      `Candidate ${readiness.candidate_available ? "YES" : "NO"} | ` +
      `Confidence ${Math.round(Number(u.overall_confidence || 0) * 100)}% | ` +
      `${u.phase || "SEARCHING"}`;
  }

  const syncBadge = $("syncBadge");
  if(syncBadge){
    syncBadge.textContent = `STATE ${String(u.state_id || "—").slice(0,6)}`;
  }

  const primaryLabel = $("immutablePrimary");
  const stateLabel = $("immutableState");
  if(primaryLabel){
    primaryLabel.textContent =
      u.primary_candidate?.english_name ||
      u.primary_candidate?.name ||
      u.primary_candidate?.printed_name ||
      "No candidate";
  }
  if(stateLabel){
    stateLabel.textContent =
      `${u.phase || "SEARCHING"} • ` +
      `${Math.round(Number(u.overall_confidence || 0) * 100)}% • ` +
      `r${u.revision || 0}`;
  }

  document.body.dataset.recognitionStateId = String(u.state_id || "");
  document.body.dataset.recognitionRevision = String(u.revision || 0);
}

function renderRecognition(r) {
  state.recognition = r || {};
  const overall = Math.round(Number(r?.overall_confidence || 0) * 100);
  const candidate = topCandidate(r);
  const locked = Boolean(r?.recognition_locked);

  const latencyValue = Number(r?.stage_timings?.total_ms);
  $("kpiLatency").textContent = Number.isFinite(latencyValue) ? `${latencyValue} ms` : "—";
  setLatencyClass(latencyValue);
  $("kpiConfidence").textContent = `${overall}%`;
  $("kpiState").textContent = r?.verification_state || (locked ? "LOCKED" : "SEARCHING");
  const matchState = r?.verification_state || (locked ? "VERIFIED" : overall >= 65 ? "COMPARING" : "SEARCHING");
  $("matchBadge").textContent = matchState;
  if($("compactMatchState")) $("compactMatchState").textContent = matchState;
  const cameraBadgeLabel = $("cameraBadge").querySelector("b");
  if(locked){
    cameraBadgeLabel.textContent = "CARD LOCKED";
    $("cameraBadge").dataset.state = "verified";
  } else if(overall >= 65){
    cameraBadgeLabel.textContent = "COMPARING";
    $("cameraBadge").dataset.state = "active";
  }
  animateConfidence(overall);

  $("devOcr").textContent = `${Math.round(Number(r?.confidence || 0) * 100)}%`;
  $("devNumber").textContent = r?.collector_number || "—";
  $("devLanguage").textContent = r?.language || "—";
  $("devArtMs").textContent = r?.artwork_index?.search_ms != null ? `${r.artwork_index.search_ms} ms` : "—";
  $("devIndex").textContent = String(r?.artwork_index?.status?.record_count || 0);
  $("devMode").textContent = r?.mode || "—";
  $("developerStatus").textContent = r?.error || `Fingerprint: ${r?.artwork_fingerprint || "—"}`;
  $("overlayName").textContent = r?.name_candidate || candidate?.name || "Waiting…";
  $("overlayNumber").textContent = r?.collector_number || candidate?.collector_number || "—";
  $("overlayHp").textContent = `HP ${r?.hp || candidate?.hp || "—"}`;
  $("overlayLanguage").textContent = r?.language || candidate?.language || "—";
  const overlayOverall = Math.max(0,Math.min(100,Math.round(Number(r?.overall_confidence || 0) * 100)));
  $("scanOverlayConfidence").textContent = `${overlayOverall}%`;
  $("scanOverlayState").textContent = r?.recognition_locked
    ? "MATCH LOCKED"
    : overlayOverall >= 50
      ? "COMPARING"
      : "SEARCHING";
  const ocrScore = Number(r?.confidence || 0) * 100;
  const artworkScore = Number(candidate?.artwork_score ?? candidate?.score ?? 0) * 100;
  const catalogRaw = r?.database_match?.confidence ?? r?.catalog_lookup?.confidence;
  const catalogScore = Number(catalogRaw || 0) * (Number(catalogRaw || 0) <= 1 ? 100 : 1);
  const languageScore = (r?.language || candidate?.language) ? 100 : 0;
  setBreakdown("breakOcr",ocrScore);
  setBreakdown("breakArtwork",artworkScore);
  setBreakdown("breakCatalog",catalogScore);
  setBreakdown("breakLanguage",languageScore);
  $("explanationBody").innerHTML = [
    artworkScore > 0 ? `Artwork similarity: <b>${Math.round(artworkScore)}%</b>` : null,
    r?.collector_number ? `Collector number detected: <b>${r.collector_number}</b>` : null,
    r?.language ? `Language detected: <b>${r.language}</b>` : null,
    r?.database_match ? `Catalog record matched.` : `Using ranked local candidates.`
  ].filter(Boolean).join("<br>");
  $("completionReference").textContent = bestOfficialImage(r,candidate) ? "Ready" : "Live Crop";
  $("completionCatalog").textContent = r?.database_match ? "Matched" : candidate ? "Candidate" : "Waiting";
  $("completionVerify").textContent = locked
    ? "Verified"
    : r?.verification_state === "REFERENCE NEEDED"
      ? "Reference Needed"
      : overall >= 65
        ? "Comparing"
        : "Searching";
  $("completionEvidence").textContent = r?.has_reference_evidence ? "Loaded" : "Missing";

  if (r?.active_set?.active_set) {
    renderActiveSet(r.active_set.active_set, r?.artwork_index?.status);
  }

  if (!candidate) {
    $("cardName").textContent = r?.name_candidate || "Waiting for card…";
    $("cardEnglishName").textContent = "English name unavailable — catalog translation needed";
    $("verifiedThumb").style.display = "none";
    $("verifiedThumbEmpty").style.display = "grid";
    $("cardSubtitle").textContent = "RareIQ will place the strongest verified candidate here.";
    $("referenceImage").style.display = "none";
    $("referenceImage").removeAttribute("src");
    $("referenceEmpty").style.display = "block";
    $("referenceEmpty").textContent = "No official reference image yet.";
  } else {
    const score = Math.round(Number(candidate.fused_score ?? candidate.score ?? 0) * 100);
    const printedName = candidate.printed_name || r?.name_candidate || candidate.name || "Unknown card";
    const englishName = candidate.english_name || candidate.canonical_name || candidate.name_en ||
      r?.database_match?.english_name || englishCatalogName(r,candidate) || null;
    $("cardName").textContent = printedName;
    $("cardEnglishName").textContent = englishName
      ? `English: ${englishName}`
      : "English name unavailable — catalog translation needed";

    const thumbUrl = bestOfficialImage(r,candidate) || `/api/camera/crop.jpg?t=${Date.now()}`;
    const thumb = $("verifiedThumb");
    const thumbEmpty = $("verifiedThumbEmpty");
    if(thumbUrl){
      thumb.onload = ()=>{ thumb.style.display="block"; thumbEmpty.style.display="none"; };
      thumb.onerror = ()=>{ thumb.style.display="none"; thumbEmpty.style.display="grid"; };
      thumb.src = `${thumbUrl}${thumbUrl.includes("?") ? "&" : "?"}t=${Date.now()}`;
    }else{
      thumb.style.display="none";
      thumbEmpty.style.display="grid";
    }
    $("cardSubtitle").textContent = `${score}% candidate confidence`;
    $("cardNumber").textContent = candidate.collector_number || r?.collector_number || "—";
    $("cardLanguage").textContent = candidate.language || r?.language || "—";
    $("cardSet").textContent = candidate.set_name || r?.database_match?.set_name || "—";
    $("cardSource").textContent = candidate.source || "local";
    $("cardRarity").textContent = candidate.rarity || r?.database_match?.rarity || "—";
    $("cardDatabase").textContent = r?.database_match ? "MATCHED" : candidate.source === "artwork_index" ? "LOCAL INDEX" : "CANDIDATE";
    $("cardHpType").textContent = [candidate.hp || r?.hp, candidate.type || candidate.card_type].filter(Boolean).join(" • ") || "—";
    $("cardIllustrator").textContent = candidate.illustrator || r?.database_match?.illustrator || "—";
    $("cardVariant").textContent = candidate.variant || candidate.rarity || "Standard";
    const matchPanel = document.querySelector(".match-panel");
    if (locked && matchPanel) {
      matchPanel.classList.remove("flash");
      void matchPanel.offsetWidth;
      matchPanel.classList.add("flash");
    }

    applyReferenceImage(candidate);
  }

  renderTimeline(r);
  renderCandidates(r);
  renderThinkingFeed(r);
  $("confidenceRing").classList.toggle("high-confidence",overall >= 95);
  if(locked && !wasRecognitionLocked){
    showMatchLock(r,candidate,overall);
  }
  wasRecognitionLocked = locked;
  maybeAutoAdd(r);
}


function updateProfessionalTelemetry(snapshot){
  const raw = snapshot?.raw_recognition || {};
  const timings = snapshot?.stage_timings || {};
  const total = Number(raw.latency_ms || raw.total_latency_ms || 0);
  const ocr = Number(timings.ocr || raw.ocr_latency_ms || 0);
  const artwork = Number(timings.artwork || raw.artwork_latency_ms || 0);
  const vector = Number(raw.global_visual_latency_ms || 0);

  $("metricTotalMs").textContent = total ? `${Math.round(total)} ms` : "— ms";
  $("metricOcrMs").textContent = ocr ? `${Math.round(ocr)} ms` : "— ms";
  $("metricArtworkMs").textContent = artwork ? `${Math.round(artwork)} ms` : "— ms";
  $("metricVectorMs").textContent = vector ? `${Math.round(vector)} ms` : "— ms";
  $("telemetryState").textContent = snapshot?.phase || "IDLE";
  $("pipelineSummary").textContent =
    `${Math.round(Number(snapshot?.overall_confidence || 0) * 100)}%`;

  const stages = snapshot?.pipeline_stages || [];
  const done = new Set(
    stages.filter(stage => stage?.state === "done")
      .map(stage => String(stage.key || "").toLowerCase())
  );
  const active = String(
    stages.find(stage => stage?.state === "active")?.key || ""
  ).toLowerCase();

  document.querySelectorAll(".pipeline-list>div").forEach(row => {
    const key = row.dataset.stage;
    row.classList.toggle("done", done.has(key));
    row.classList.toggle("active", active === key);
    row.querySelector("b").textContent = done.has(key)
      ? "DONE"
      : active === key
        ? "LIVE"
        : "WAIT";
  });

  const lines = [];
  if(snapshot?.name_candidate) lines.push(`Name: ${snapshot.name_candidate}`);
  if(snapshot?.collector_number) lines.push(`Number: ${snapshot.collector_number}`);
  if(snapshot?.language) lines.push(`Language: ${snapshot.language}`);
  if(snapshot?.primary_candidate?.set_name) lines.push(`Set: ${snapshot.primary_candidate.set_name}`);
  if(snapshot?.primary_candidate?.rarity) lines.push(`Rarity: ${snapshot.primary_candidate.rarity}`);
  lines.push(`Phase: ${snapshot?.phase || "SEARCHING"}`);

  $("aiActivityLog").innerHTML = lines.map(line => `<div>${line}</div>`).join("");
}

window.RecognitionController = Object.freeze({
  render: renderUnifiedRecognition,
  renderPanel: renderRecognition,
  renderCandidates,
  renderTimeline,
  renderThinking: renderThinkingFeed,
  updateProfessionalTelemetry,
});
