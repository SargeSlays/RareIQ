/*
 * CatalogController
 * Owns active-set selection, set import and artwork-index rebuilding.
 */
async function loadSets() {
  const result = await fetch("/api/sets", {cache:"no-store"}).then(r => r.json());
  const select = $("activeSetSelect");
  select.innerHTML = "";
  (result.sets || []).forEach(set => {
    const option = document.createElement("option");
    option.value = set.id;
    option.textContent = `${set.game} • ${set.language} • ${set.name}`;
    select.appendChild(option);
  });
  if (result.status?.active_set_id) select.value = result.status.active_set_id;
  renderActiveSet(result.status?.active_set, {record_count:0});
}

async function applyActiveSet() {
  const result = await post("/api/sets/active", {set_id:$("activeSetSelect").value});
  if (result.ok) renderActiveSet(result.active_set, result.index_status);
  $("setStatus").textContent = result.ok ? `Loaded ${result.active_set?.name || "set"}.` : result.error || "Failed.";
}

async function importLiveSet() {
  $("catalogStatus").textContent = "Connecting to TCGdex and importing official data…";
  const result = await post("/api/live-catalog/import-set", {
    set_id:$("liveSetId").value.trim(),
    language:$("liveSetLanguage").value,
    max_cards:$("liveSetLimit").value ? Number($("liveSetLimit").value) : null
  });
  $("catalogStatus").textContent = result.ok
    ? `Imported ${result.imported} cards from ${result.set_name}. Skipped ${result.skipped}. Index: ${result.index_status?.record_count || 0}.`
    : `Import failed: ${result.error || "Unknown error"}`;
}

async function rebuildIndex() {
  const result = await post("/api/artwork-index/rebuild");
  $("developerStatus").textContent = result.ok
    ? `Index rebuilt: ${result.status?.record_count || 0} references.`
    : result.error || "Rebuild failed.";
}


async function loadMasterCatalogStatus(){
  try{
    const result = await fetch("/api/catalog-engine/status", {cache:"no-store"}).then(r=>r.json());
    const status = result.catalog_engine || {};
    $("masterCoverageBadge").textContent =
      `${status.cards || 0} cards • ${status.coverage_percent || 0}% images`;

    const config = status.config || {};
    if(document.activeElement !== $("dropboxLocalPath")){
      $("dropboxLocalPath").value = config.dropbox_local_path || "";
    }
    $("dropboxMirrorEnabled").checked = Boolean(config.mirror_enabled);

    const container = $("masterCatalogSets");
    const sets = status.set_manifests || [];
    container.innerHTML = sets.length
      ? sets.map(set => `
          <div class="master-set-row">
            <b>${set.set_name || set.set_id}</b>
            <span>${set.cards || 0} cards</span>
            <span>${set.coverage_percent || 0}%</span>
          </div>
        `).join("")
      : '<div class="recent-empty">No master sets imported yet.</div>';
  }catch(error){
    $("catalogStatus").textContent = "Master catalog status unavailable.";
  }
}

async function importMasterCatalogSet(){
  const setId = $("liveSetId").value.trim();
  if(!setId){
    $("catalogStatus").textContent = "Enter the exact TCGdex set ID first.";
    return;
  }

  $("catalogStatus").textContent =
    "Downloading metadata and full-resolution reference images…";

  const result = await post("/api/catalog-engine/import-set", {
    set_id: setId,
    language: $("liveSetLanguage").value,
    max_cards: $("liveSetLimit").value
      ? Number($("liveSetLimit").value)
      : null
  });

  $("catalogStatus").textContent = result.ok
    ? `Catalog complete: ${result.cards} cards, ${result.images} images, ` +
      `${result.coverage_percent}% coverage. Index: ` +
      `${result.index_status?.record_count || 0}.`
    : `Catalog build failed: ${result.error || "Unknown error"}`;

  await loadMasterCatalogStatus();
  await loadSets();
}

async function saveCatalogStorage(){
  const result = await post("/api/catalog-engine/config", {
    dropbox_local_path: $("dropboxLocalPath").value.trim(),
    mirror_enabled: $("dropboxMirrorEnabled").checked,
    preferred_language: $("liveSetLanguage").value
  });

  $("catalogStatus").textContent = result.ok
    ? "Catalog storage settings saved."
    : result.error || "Unable to save storage settings.";

  await loadMasterCatalogStatus();
}


async function loadPokemonMasterStatus(){
  try{
    const result = await fetch("/api/pokemon-master/status", {cache:"no-store"}).then(r=>r.json());
    const status = result.pokemon_master || {};
    window.__professionalMasterStatus = status;

    $("worldBuildPhase").textContent = status.phase || "IDLE";
    $("worldSets").textContent =
      `${status.sets_completed || 0}/${status.sets_discovered || 0}`;
    $("worldCards").textContent = String(status.cards || 0);
    $("worldImages").textContent = String(status.images || 0);
    $("worldCoverage").textContent = `${status.coverage_percent || 0}%`;

    const discovered = Number(status.sets_discovered || 0);
    const completed = Number(status.sets_completed || 0);
    const progress = discovered
      ? Math.min(100, Math.round(completed / discovered * 100))
      : 0;
    $("worldProgressFill").style.width = `${progress}%`;

    $("worldCurrentSet").textContent = status.busy
      ? `${status.provider || "provider"} • ${status.language || "language"} • ` +
        `${status.set_name || status.set_id || "Preparing…"}`
      : status.phase === "COMPLETE"
        ? `Complete: ${completed} sets, ${status.cards || 0} cards, ` +
          `${status.images || 0} images.`
        : status.errors?.length
          ? status.errors[status.errors.length - 1]
          : "Ready to discover the worldwide Pokémon catalog.";
  }catch(error){
    $("worldCurrentSet").textContent =
      "Pokémon Master Database status unavailable.";
  }
}

async function discoverPokemonWorld(){
  $("worldCurrentSet").textContent =
    "Discovering supported Pokémon sets from every provider…";

  const result = await post("/api/pokemon-master/discover", {
    languages: null,
    provider_ids: null,
    resume: true,
    max_sets: null
  });

  $("worldCurrentSet").textContent = result.ok
    ? `Discovered ${result.count || 0} provider set records.`
    : result.error || "Set discovery failed.";

  await loadPokemonMasterStatus();
}

async function buildPokemonWorld(){
  $("worldCurrentSet").textContent =
    "Starting the worldwide Pokémon database build…";

  const result = await post("/api/pokemon-master/build", {
    languages: null,
    provider_ids: null,
    resume: true,
    max_sets: null
  });

  $("worldCurrentSet").textContent = result.ok
    ? "Build started. RareIQ will resume completed sets automatically."
    : result.error || "Unable to start database build.";

  await loadPokemonMasterStatus();
}

async function cancelPokemonWorld(){
  await post("/api/pokemon-master/cancel");
  $("worldCurrentSet").textContent = "Stopping after the current card or set…";
}


async function loadPokemonVisionStatus(){
  try{
    const result = await fetch("/api/pokemon-vision/status", {cache:"no-store"}).then(r=>r.json());
    const visual = result.visual_index || {};
    const sync = result.auto_sync || {};
    window.__professionalVisionStatus = result;
    const config = sync.config || {};

    $("visionEnginePhase").textContent = sync.phase || "IDLE";
    $("visionIndexRecords").textContent = String(visual.records || 0);
    $("visionIndexDimensions").textContent = String(visual.dimensions || 0);
    $("visionLastBuild").textContent = visual.last_build
      ? new Date(visual.last_build * 1000).toLocaleTimeString()
      : "Never";
    $("visionAutoSync").textContent = config.enabled ? "On" : "Off";
    $("visionAutoSyncEnabled").checked = Boolean(config.enabled);
    $("visionSyncHours").value = config.interval_hours || 24;

    renderProfessionalBuildStatus(window.__professionalMasterStatus || {}, result);

    $("visionEngineStatus").textContent = sync.error
      ? `Sync error: ${sync.error}`
      : visual.ready
        ? `Global visual search ready with ${visual.records || 0} indexed card images.`
        : sync.phase === "BUILDING"
          ? "Downloading and normalizing the worldwide Pokémon database…"
          : sync.phase === "INDEXING"
            ? "Building the global image-search index…"
            : "Ready to sync the Pokémon database and visual index.";
  }catch(error){
    $("visionEngineStatus").textContent =
      "Pokémon AI Vision Engine status unavailable.";
  }
}

async function syncPokemonVisionNow(){
  $("visionEngineStatus").textContent =
    "Starting provider discovery, database sync, and visual indexing…";
  const result = await post("/api/pokemon-vision/sync-now");
  $("visionEngineStatus").textContent = result.ok
    ? "Pokémon database sync started in the background."
    : result.error || "Unable to start sync.";
  await loadPokemonVisionStatus();
}

async function rebuildPokemonVisionIndex(){
  $("visionEngineStatus").textContent =
    "Rebuilding the global visual-search index…";
  const result = await post("/api/pokemon-vision/rebuild");
  $("visionEngineStatus").textContent = result.ok
    ? `Visual index complete: ${result.records || 0} images, ` +
      `${result.dimensions || 0} dimensions.`
    : result.error || "Visual index build failed.";
  await loadPokemonVisionStatus();
}

async function stopPokemonVisionSync(){
  await post("/api/pokemon-vision/stop-sync");
  $("visionEngineStatus").textContent =
    "Stopping after the current provider operation…";
}

async function savePokemonVisionConfig(){
  const result = await post("/api/pokemon-vision/config", {
    enabled: $("visionAutoSyncEnabled").checked,
    interval_hours: Number($("visionSyncHours").value || 24)
  });
  $("visionEngineStatus").textContent = result.ok
    ? "Pokémon auto-sync settings saved."
    : result.error || "Unable to save auto-sync settings.";
  await loadPokemonVisionStatus();
}


function renderProfessionalBuildStatus(master, vision){
  const sync = vision?.auto_sync || {};
  const visual = vision?.visual_index || {};
  const discovered = Number(master?.sets_discovered || 0);
  const completed = Number(master?.sets_completed || 0);
  const failed = Number(master?.sets_failed || 0);
  const percent = discovered
    ? Math.min(100, Math.round((completed + failed) / discovered * 100))
    : 0;

  const busy = Boolean(master?.busy) ||
    !["IDLE","COMPLETE","FAILED"].includes(sync.phase || "IDLE");

  $("globalBuildDot").classList.toggle("active", busy);
  $("globalBuildTitle").textContent = busy
    ? `${sync.phase || master.phase || "BUILDING"}`
    : sync.phase === "COMPLETE"
      ? "Database build complete"
      : "Database idle";
  $("globalBuildDetail").textContent = master?.busy
    ? `${master.provider || "provider"} • ${master.language || "language"} • ${master.set_name || master.set_id || "Preparing"}`
    : visual.ready
      ? `${visual.records || 0} indexed images ready for recognition`
      : "Press Sync & Build Everything to begin.";
  $("globalBuildPercent").textContent = `${percent}%`;
  $("globalBuildProgressFill").style.width = `${percent}%`;

  const tasks = [];
  if(master?.busy){
    tasks.push({
      title: master.set_name || master.set_id || "Importing set",
      detail: `${master.provider || "provider"} / ${master.language || "language"}`
    });
  }
  if(sync.phase === "DISCOVERING"){
    tasks.push({title:"Discovering provider sets",detail:"Worldwide Pokémon catalog"});
  }
  if(sync.phase === "INDEXING"){
    tasks.push({title:"Building visual index",detail:`${visual.records || 0} images indexed`});
  }

  $("taskQueueCount").textContent = `${tasks.length} active`;
  $("taskQueue").innerHTML = tasks.length
    ? tasks.map(task => `
        <div class="task-item">
          <i></i><b>${task.title}</b><span>${task.detail}</span>
        </div>
      `).join("")
    : '<div class="task-empty">No active jobs.</div>';
}


function formatStorageBytes(value){
  const bytes = Number(value || 0);
  if(bytes <= 0) return "0 B";
  const units = ["B","KB","MB","GB","TB"];
  const index = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  return `${(bytes / Math.pow(1024, index)).toFixed(index >= 3 ? 2 : 1)} ${units[index]}`;
}

async function loadStorageStatus(){
  try{
    const result = await fetch("/api/storage/status", {cache:"no-store"}).then(r=>r.json());
    const s = result.storage || {};
    const total = Number(s.total_bytes || 0);
    const used = Number(s.used_bytes || 0);
    const percent = total ? Math.round(used / total * 100) : 0;
    $("storageRootPath").textContent = s.root || "Unavailable";
    $("storageHealth").textContent = s.ready ? "HEALTHY" : "ERROR";
    $("storageTotal").textContent = formatStorageBytes(total);
    $("storageUsed").textContent = formatStorageBytes(used);
    $("storageFree").textContent = formatStorageBytes(s.free_bytes || 0);
    $("storageProgressFill").style.width = `${percent}%`;
  }catch(error){
    $("storageRootPath").textContent = "Unable to read storage status.";
    $("storageHealth").textContent = "ERROR";
  }
}


function formatBuilderEta(seconds){
  const value = Number(seconds);
  if(!Number.isFinite(value) || value < 0) return "—";
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  if(hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

async function loadMasterBuilderStatus(){
  try{
    const result = await fetch("/api/master-builder/status", {cache:"no-store"}).then(r=>r.json());
    const builder = result.builder || {};
    const discovered = Number(builder.sets_discovered || 0);
    const completed = Number(builder.sets_completed || 0);
    const failed = Number(builder.sets_failed || 0);
    const processed = completed + failed;
    const percent = discovered
      ? Math.min(100, Math.round(processed / discovered * 100))
      : 0;

    $("visionEnginePhase").textContent = builder.phase || "IDLE";
    $("builderSets").textContent = `${processed}/${discovered}`;
    $("builderCards").textContent = String(builder.cards || 0);
    $("builderImages").textContent = String(builder.images || 0);
    $("builderSpeed").textContent = `${Number(builder.cards_per_second || 0).toFixed(1)}/s`;
    $("builderEta").textContent = formatBuilderEta(builder.eta_seconds);

    const currentProcessed = Number(builder.current_set_processed || 0);
    const currentTotal = Number(builder.current_set_total || 0);
    const currentPercent = currentTotal
      ? Math.min(100, Math.round(currentProcessed / currentTotal * 100))
      : 0;
    $("currentSetProgressTitle").textContent =
      builder.current_set_name || "No active set";
    $("currentSetProgressText").textContent =
      `${currentProcessed} / ${currentTotal} cards`;
    $("currentSetProgressPercent").textContent = `${currentPercent}%`;
    $("currentSetProgressFill").style.width = `${currentPercent}%`;

    $("visionIndexRecords").textContent =
      String(builder.indexed_images || builder.visual_index?.records || 0);

    $("globalBuildDot").classList.toggle("active", Boolean(builder.busy));
    $("globalBuildTitle").textContent = builder.busy
      ? builder.phase || "BUILDING"
      : builder.phase === "COMPLETE"
        ? "Pokémon database ready"
        : builder.phase === "FAILED"
          ? "Build failed"
          : "Database idle";

    $("globalBuildDetail").textContent = builder.busy
      ? `${builder.current_provider || "provider"} • ` +
        `${builder.current_language || "language"} • ` +
        `${builder.current_set_name || builder.current_set_id || "Preparing"}`
      : builder.last_error
        ? builder.last_error
        : builder.last_completed
          ? `Last completed: ${builder.last_completed}`
          : "Press Build Pokémon Master Database to begin.";

    $("globalBuildPercent").textContent = `${percent}%`;
    $("globalBuildProgressFill").style.width = `${percent}%`;

    const activity = builder.activity || [];
    $("taskQueueCount").textContent =
      `${builder.queue_remaining || 0} queued`;
    $("taskQueue").innerHTML = activity.length
      ? activity.slice(-10).reverse()
          .map(line => `<div class="builder-activity-line">${line}</div>`)
          .join("")
      : '<div class="task-empty">No build activity yet.</div>';

    $("visionEngineStatus").textContent = builder.busy
      ? `Building on ${builder.storage?.catalog_root || "configured storage"}`
      : builder.phase === "COMPLETE"
        ? `Complete: ${builder.cards || 0} cards, ${builder.images || 0} images, ` +
          `${builder.indexed_images || 0} indexed.`
        : builder.last_error || "Ready to build the Pokémon Master Database.";
  }catch(error){
    $("visionEngineStatus").textContent =
      "Master Database Builder status unavailable.";
  }
}

async function startMasterDatabaseBuild(){
  $("visionEngineStatus").textContent =
    "Starting discovery and resumable Pokémon database build…";
  const result = await post("/api/master-builder/start");
  $("visionEngineStatus").textContent = result.ok
    ? "Master Database Builder started."
    : result.error || "Unable to start the database build.";
  await loadMasterBuilderStatus();
}

async function stopMasterDatabaseBuild(){
  await post("/api/master-builder/stop");
  $("visionEngineStatus").textContent =
    "Stop requested. Progress will be preserved.";
  await loadMasterBuilderStatus();
}

async function rebuildMasterVisualIndex(){
  $("visionEngineStatus").textContent =
    "Rebuilding the global visual index…";
  const result = await post("/api/master-builder/rebuild-index");
  $("visionEngineStatus").textContent = result.ok
    ? `Visual index ready with ${result.records || 0} images.`
    : result.error || "Visual index rebuild failed.";
  await loadMasterBuilderStatus();
}


function renderProviderResult(prefix, result){
  const dot = $(`${prefix}ProviderDot`);
  const status = $(`${prefix}ProviderStatus`);
  const online = Boolean(result?.online);
  dot.classList.toggle("online", online);
  dot.classList.toggle("error", !online);
  status.textContent = online
    ? `Online • ${Math.round(Number(result.latency_ms || 0))} ms`
    : result?.error || "Offline";
}

async function loadProviderStatus(){
  try{
    const result = await fetch("/api/providers/status", {cache:"no-store"}).then(r=>r.json());
    const diagnostics = result.diagnostics || {};
    const providers = diagnostics.providers || {};
    renderProviderResult("tcgdex", providers.tcgdex);
    renderProviderResult("pokemontcg", providers.pokemontcg);

    const keyLoaded = Boolean(
      diagnostics.secrets?.pokemontcg_api_key_loaded
    );
    $("apiKeyProviderDot").classList.toggle("online", keyLoaded);
    $("apiKeyProviderDot").classList.toggle("error", !keyLoaded);
    $("apiKeyProviderStatus").textContent = keyLoaded
      ? "Loaded securely"
      : "Optional • lower limits";
  }catch(error){
    $("tcgdexProviderStatus").textContent = "Status unavailable";
    $("pokemontcgProviderStatus").textContent = "Status unavailable";
  }
}

async function checkProvidersNow(){
  $("tcgdexProviderStatus").textContent = "Checking…";
  $("pokemontcgProviderStatus").textContent = "Checking…";
  const result = await post("/api/providers/check");
  const providers = result.providers || {};
  renderProviderResult("tcgdex", providers.tcgdex);
  renderProviderResult("pokemontcg", providers.pokemontcg);

  const keyLoaded = Boolean(
    result.secrets?.pokemontcg_api_key_loaded
  );
  $("apiKeyProviderDot").classList.toggle("online", keyLoaded);
  $("apiKeyProviderDot").classList.toggle("error", !keyLoaded);
  $("apiKeyProviderStatus").textContent = keyLoaded
    ? "Loaded securely"
    : "Optional • lower limits";
}


function selectedFastPipelineLanguages(){
  const languages = [];
  if($("pipelineEnglish")?.checked) languages.push("English");
  if($("pipelineJapanese")?.checked) languages.push("Japanese");
  if($("pipelineTraditionalChinese")?.checked){
    languages.push("Traditional Chinese");
  }
  return languages;
}

async function loadFastPipelineStatus(){
  try{
    const result = await fetch("/api/fast-pipeline/status", {
      cache: "no-store"
    }).then(response => response.json());
    const pipeline = result.pipeline || {};
    const metadata = pipeline.metadata || {};
    const images = pipeline.images || {};

    $("fastMetadataPhase").textContent = metadata.phase || "IDLE";
    $("fastMetadataStats").textContent =
      `${metadata.sets_completed || 0}/${metadata.sets_discovered || 0} sets • ` +
      `${metadata.cards || 0} cards`;

    $("fastImagePhase").textContent = images.phase || "IDLE";
    const imageProcessed =
      Number(images.completed || 0) +
      Number(images.skipped || 0) +
      Number(images.failed || 0);
    $("fastImageStats").textContent =
      `${imageProcessed} / ${images.queued || 0} images`;
    $("fastImageRate").textContent =
      `${Number(images.mb_per_second || 0).toFixed(2)} MB/s`;
    $("fastImageEta").textContent =
      `ETA ${formatBuilderEta(images.eta_seconds)}`;

    const busy = Boolean(metadata.busy || images.busy);
    $("globalBuildDot").classList.toggle("active", busy);
    $("globalBuildTitle").textContent = metadata.busy
      ? `Metadata • ${metadata.phase}`
      : images.busy
        ? `HD Artwork • ${images.phase}`
        : pipeline.catalog_ready
          ? "Metadata catalog ready"
          : "Fast pipeline idle";

    $("globalBuildDetail").textContent = metadata.busy
      ? `${metadata.current_language || "Language"} • ` +
        `${metadata.current_set || "Preparing"}`
      : images.busy
        ? `${images.current || "Downloading"} • ` +
          `${images.workers || 0} workers`
        : metadata.last_error || images.last_error ||
          "Build metadata first, then download HD artwork separately.";

    const metadataDone =
      Number(metadata.sets_completed || 0) +
      Number(metadata.sets_failed || 0);
    const metadataTotal = Number(metadata.sets_discovered || 0);
    const imageTotal = Number(images.queued || 0);
    const metadataPercent = metadataTotal
      ? Math.round(metadataDone / metadataTotal * 100)
      : pipeline.catalog_ready ? 100 : 0;
    const imagePercent = imageTotal
      ? Math.round(imageProcessed / imageTotal * 100)
      : 0;
    const percent = metadata.busy
      ? metadataPercent
      : images.busy
        ? imagePercent
        : pipeline.catalog_ready
          ? 100
          : 0;

    $("globalBuildPercent").textContent = `${percent}%`;
    $("globalBuildProgressFill").style.width = `${percent}%`;

    const activity = pipeline.activity || [];
    $("taskQueueCount").textContent = `${activity.length} events`;
    $("taskQueue").innerHTML = activity.length
      ? activity.slice(-12).reverse()
          .map(line => `<div class="builder-activity-line">${line}</div>`)
          .join("")
      : '<div class="task-empty">No pipeline activity yet.</div>';

    $("visionEngineStatus").textContent = metadata.busy
      ? "Building lightweight metadata catalog. HD artwork is not blocking."
      : images.busy
        ? "Downloading missing HD artwork in parallel. Existing files are skipped."
        : pipeline.catalog_ready
          ? "Metadata catalog ready. You can scan while HD artwork downloads."
          : "Ready for the metadata-first build.";
  }catch(error){
    $("visionEngineStatus").textContent =
      "Fast Pipeline status unavailable.";
  }
}

async function startFastMetadata(){
  const languages = selectedFastPipelineLanguages();
  if(!languages.length){
    $("visionEngineStatus").textContent =
      "Select at least one supported language.";
    return;
  }
  const result = await post(
    "/api/fast-pipeline/metadata/start",
    {languages}
  );
  $("visionEngineStatus").textContent = result.ok
    ? "Metadata pipeline started."
    : result.error || "Unable to start metadata pipeline.";
  await loadFastPipelineStatus();
}

async function startFastImages(){
  const workers = Math.max(
    2,
    Math.min(24, Number($("pipelineWorkers")?.value || 12))
  );
  const result = await post(
    "/api/fast-pipeline/images/start",
    {workers}
  );
  $("visionEngineStatus").textContent = result.ok
    ? "HD artwork backfill started."
    : result.error || "Unable to start HD artwork.";
  await loadFastPipelineStatus();
}

async function stopFastPipeline(){
  await post("/api/fast-pipeline/stop");
  $("visionEngineStatus").textContent =
    "Stop requested. Completed metadata and images are preserved.";
  await loadFastPipelineStatus();
}

async function buildFastVisualIndex(){
  const result = await post("/api/fast-pipeline/index");
  $("visionEngineStatus").textContent = result.ok
    ? `Visual index ready with ${result.records || 0} records.`
    : result.error || "Visual index build failed.";
  await loadFastPipelineStatus();
}


async function loadWarRoomStatus(){
  try{
    const result = await fetch("/api/war-room/status", {
      cache: "no-store"
    }).then(response => response.json());
    const room = result.war_room || {};
    const systems = room.systems || {};
    const metrics = room.metrics || {};

    $("warMetadata").textContent =
      systems.metadata_pipeline || "IDLE";
    $("warImages").textContent =
      systems.hd_artwork || "IDLE";
    $("warVisual").textContent =
      String(systems.visual_index || "not_ready").replaceAll("_", " ").toUpperCase();
    $("warAssets").textContent =
      String(metrics.registered_assets || 0);
    $("warPlugins").textContent =
      String((room.plugins || []).length);
    $("warFusion").textContent =
      String(systems.recognition_fusion || "ready").toUpperCase();

    $("warRoomStatus").textContent =
      `${metrics.metadata_cards || 0} metadata cards • ` +
      `${metrics.visual_records || 0} visual records • ` +
      `${metrics.registered_assets || 0} registered assets`;
  }catch(error){
    $("warRoomStatus").textContent =
      "WAR ROOM status unavailable.";
  }
}

async function scanAssetLibrary(){
  $("warRoomStatus").textContent =
    "Validating local image library…";
  const result = await post("/api/assets/scan");
  $("warRoomStatus").textContent = result.ok
    ? `Checked ${result.checked || 0}: ` +
      `${result.valid || 0} valid, ` +
      `${result.corrupt || 0} corrupt, ` +
      `${result.too_small || 0} too small.`
    : result.error || "Asset scan failed.";
  await loadWarRoomStatus();
}

async function runFusionBenchmark(){
  $("warRoomStatus").textContent =
    "Running 10,000 recognition-fusion iterations…";
  const result = await post("/api/benchmarks/fusion");
  $("warRoomStatus").textContent = result.ok
    ? `Fusion benchmark: ${result.mean_ms} ms mean, ` +
      `${result.p95_ms} ms p95.`
    : result.error || "Benchmark failed.";
}


async function loadIndexActivationStatus(){
  try{
    const result = await fetch("/api/index-activation/status", {
      cache: "no-store"
    }).then(response => response.json());
    const activation = result.activation || {};
    const visual = activation.visual_index || {};
    const percent = Number(visual.progress_percent || 0);

    $("indexActivationPhase").textContent =
      activation.phase || "IDLE";
    $("indexActivationDetail").textContent = activation.busy
      ? `${visual.processed_cards || 0}/${visual.discovered_cards || 0} cards • ` +
        `${visual.records || 0} indexed • ` +
        `${visual.skipped_missing || 0} missing`
      : visual.ready
        ? `${visual.records || 0} indexed cards ready for recognition.`
        : activation.last_error ||
          "Waiting to build from local artwork.";
    $("indexActivationPercent").textContent = `${percent}%`;
    $("indexActivationFill").style.width = `${percent}%`;

    $("warVisual").textContent = visual.ready
      ? `READY • ${visual.records || 0}`
      : activation.busy
        ? `BUILDING • ${percent}%`
        : "NOT READY";
  }catch(error){
    $("indexActivationDetail").textContent =
      "Index activation status unavailable.";
  }
}

async function activateRecognitionIndex(){
  $("indexActivationDetail").textContent =
    "Discovering local metadata and artwork…";
  const result = await post("/api/index-activation/start");
  $("indexActivationDetail").textContent = result.ok
    ? "Recognition index activation started."
    : result.error || "Unable to activate recognition index.";
  await loadIndexActivationStatus();
}


function renderHealthState(name, state){
  const dot = $(`health${name}Dot`);
  const label = $(`health${name}`);
  const ok = Boolean(state?.ok);
  dot.classList.toggle("online", ok);
  dot.classList.toggle("warning", !ok);
  label.textContent = String(state?.status || "unknown")
    .replaceAll("_", " ")
    .toUpperCase();
}

async function loadSystemHealth(){
  try{
    const result = await fetch("/api/system/health", {
      cache: "no-store"
    }).then(response => response.json());
    const health = result.health || {};
    const systems = health.systems || {};
    const metrics = health.metrics || {};

    renderHealthState("Camera", systems.camera);
    renderHealthState("Recognition", systems.recognition);
    renderHealthState("Index", systems.visual_index);
    renderHealthState("Metadata", systems.metadata);
    renderHealthState("Providers", systems.providers);
    renderHealthState("Jobs", systems.job_queue);

    $("healthIndexedCards").textContent =
      String(metrics.indexed_cards || 0);
    $("healthLocalImages").textContent =
      String(metrics.available_local_images || 0);
    $("healthUnindexed").textContent =
      String(metrics.unindexed_local_images || 0);
    $("healthQueuedJobs").textContent =
      String(metrics.queued_jobs || 0);

    $("autoIndexToggle").checked =
      health.auto_index_enabled !== false;
    $("systemHealthOverall").textContent =
      health.healthy ? "HEALTHY" : "ATTENTION";

    const currentJob = health.current_job;
    $("systemHealthStatus").textContent = currentJob
      ? `${currentJob.title} • ${currentJob.status}`
      : metrics.unindexed_local_images > 0
        ? `${metrics.unindexed_local_images} local images are waiting to be indexed.`
        : "All core systems are synchronized.";

    // Directly correct the global Indexed Cards metric.
    const indexedMetric =
      document.querySelector('[data-metric="indexed-cards"]') ||
      document.getElementById("indexedCards");
    if(indexedMetric){
      indexedMetric.textContent = String(metrics.indexed_cards || 0);
    }
  }catch(error){
    $("systemHealthStatus").textContent =
      "System health status unavailable.";
  }
}

async function optimizeRareIQLibrary(){
  const result = await post("/api/library/optimize");
  $("systemHealthStatus").textContent = result.ok
    ? "Library optimization queued."
    : result.error || "Unable to queue optimization.";
  await loadSystemHealth();
}

async function runIncrementalIndex(){
  const result = await post("/api/index/incremental");
  $("systemHealthStatus").textContent = result.ok
    ? "Incremental index update queued."
    : result.error || "Unable to queue index update.";
  await loadSystemHealth();
}

async function toggleAutoIndex(){
  const enabled = Boolean($("autoIndexToggle")?.checked);
  const result = await post(`/api/system/auto-index/${enabled}`);
  $("systemHealthStatus").textContent = result.ok
    ? `Auto-index ${enabled ? "enabled" : "disabled"}.`
    : result.error || "Unable to update auto-index.";
}


async function loadIntelligenceStatus(){
  try{
    const result = await fetch("/api/intelligence/status", {
      cache: "no-store"
    }).then(response => response.json());
    $("learningQueueCount").textContent =
      String(result.learning_queue?.queued || 0);
    $("intelligenceIndexedCards").textContent =
      String(result.visual_index?.records || 0);
    $("intelligenceCoreState").textContent =
      result.visual_index?.ready ? "MISSION READY" : "INDEX REQUIRED";
  }catch(error){
    $("intelligenceCoreStatus").textContent =
      "Intelligence status unavailable.";
  }
}

async function runIntelligenceBenchmark(){
  $("intelligenceCoreStatus").textContent =
    "Running X7 vision and ranking benchmark…";
  const result = await post("/api/intelligence/benchmark");
  $("intelligenceCoreStatus").textContent = result.ok
    ? `Vision ${result.vision_mean_ms} ms mean • ` +
      `Ranking ${result.ranking_mean_ms} ms mean • ` +
      `Top confidence ${(
        Number(result.top_candidate?.fused_score || 0) * 100
      ).toFixed(1)}%`
    : result.error || "X7 benchmark failed.";
}

window.CatalogController = Object.freeze({
  loadSets,
  applyActiveSet,
  importLiveSet,
  rebuildIndex,
  renderStatus: renderCatalogStatus,
  loadMasterCatalogStatus,
  importMasterCatalogSet,
  saveCatalogStorage,
  loadPokemonMasterStatus,
  discoverPokemonWorld,
  buildPokemonWorld,
  cancelPokemonWorld,
  loadPokemonVisionStatus,
  syncPokemonVisionNow,
  rebuildPokemonVisionIndex,
  stopPokemonVisionSync,
  savePokemonVisionConfig,
  renderProfessionalBuildStatus,
  loadStorageStatus,
  loadMasterBuilderStatus,
  startMasterDatabaseBuild,
  stopMasterDatabaseBuild,
  rebuildMasterVisualIndex,
  loadProviderStatus,
  checkProvidersNow,
  loadFastPipelineStatus,
  startFastMetadata,
  startFastImages,
  stopFastPipeline,
  buildFastVisualIndex,
  loadWarRoomStatus,
  scanAssetLibrary,
  runFusionBenchmark,
  loadIndexActivationStatus,
  activateRecognitionIndex,
  loadSystemHealth,
  optimizeRareIQLibrary,
  runIncrementalIndex,
  toggleAutoIndex,
  loadIntelligenceStatus,
  runIntelligenceBenchmark,
});
