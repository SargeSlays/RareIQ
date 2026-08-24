from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")


def test_toolbar_switches_between_single_and_multi_card_recognition():
    assert 'id="recognitionModeSelect"' in HTML
    assert '<option value="single">Single Card</option>' in HTML
    assert '<option value="six-card-grid">Multi-Card Grid</option>' in HTML
    assert 'onclick="captureRecognitionMode()"' in HTML
    assert JS.count('let studioXRecognitionMode="single"') == 1
    assert 'function setRecognitionMode(mode)' in JS
    assert 'function syncRecognitionModeWorkspace()' in JS
    assert 'document.querySelectorAll(".multi-card-suppressed").forEach' in JS
    assert 'requestAnimationFrame(()=>syncRecognitionModeWorkspace())' in JS
    assert 'setUI4InspectorView("current",false)' in JS


def test_right_inspector_has_twelve_isolated_result_slots():
    assert HTML.count("data-multi-card-slot=") == 12
    assert 'id="multiCardCaptureButton"' in HTML
    assert 'id="multiCardSummary"' in HTML
    assert 'id="multiCardHeldNotice"' in HTML
    assert "Last verified profile retained" in HTML
    assert 'id="multiCardUniqueVariants"' in HTML
    assert 'id="multiCardCameraOverlay"' in HTML
    assert 'body.studiox-ui4[data-recognition-mode="six-card-grid"]' in CSS
    assert '"multi-card-suppressed"' in JS
    assert 'api("/api/multi-card/capture"' in JS
    assert "unique_variants:uniqueVariants" in JS
    assert "renderMultiCardCameraOverlay" in JS
    assert "STUDIOX_RECOGNITION_MODE_KEY" in JS
    assert "STUDIOX_UNIQUE_VARIANTS_KEY" in JS
    assert "STUDIOX_MULTI_CARD_COUNT_KEY" in JS
    assert "multiCardReferenceImage" in JS
    assert "toggleMultiCardOutput" in JS
    assert 'multiCardHeldNotice.hidden=!held' in JS
    assert 'api("/api/multi-card/status")' in JS
    assert 'href="/overlay/multi-card"' in HTML
    assert '"Temporally verified"' in JS
    assert '`Confirming ${temporalProgress}/${Number(item.temporal_confirmation_required||2)}`' in JS
    assert ".multi-card-verification" in CSS
    assert 'className="multi-card-facts"' in JS
    for label in ('"Card #"', '"Set"', '"Confidence"', '"Status"', '"Language"'):
        assert label in JS
    assert ".multi-card-facts" in CSS
    assert "font-size:14px" in CSS
    assert "is-temporal-verified" in CSS
    assert '@app.get("/overlay/multi-card")' in SERVER


def test_multi_card_api_contract_is_exposed():
    assert '@app.get("/api/multi-card/status")' in SERVER
    assert '@app.post("/api/multi-card/capture")' in SERVER
    assert '@app.post("/api/multi-card/select")' in SERVER
    assert 'rare_intelligence = await current_pokedex_entry()' in SERVER
    assert '"rare_intelligence": rare_intelligence' in SERVER
    assert "if(payload.rare_intelligence)" in JS
    assert "renderPokedexPayload(studioXPokedexPayload)" in JS
    assert "orchestrator.multi_card_recognition.capture" in SERVER
    assert "for attempt in range(6)" in SERVER
    assert "if count > best_count" in SERVER
    assert "if count >= max_cards" in SERVER
    assert "detect_candidates" in SERVER
    assert "detections=best_detections" in SERVER
    assert "setTimeout(loadMultiCardStatus,80)" in JS


def test_single_card_can_pick_one_numbered_region_from_crowded_table():
    assert 'id="singleCardPickerButton"' in HTML
    assert 'api("/api/single-card/regions")' in JS
    assert 'api(`/api/single-card/pick/${Number(slot)}`' in JS
    assert "recognizePickedSingleCard" in JS
    assert '@app.get("/api/single-card/regions")' in SERVER
    assert '@app.post("/api/single-card/pick/{slot}")' in SERVER
