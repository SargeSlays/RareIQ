from __future__ import annotations

import json

from rareiq.services.set_catalog_service import SetCatalogService


def test_manual_set_lock_is_persistent_and_strict(tmp_path):
    path = tmp_path / "sets.json"
    path.write_text(json.dumps({
        "version": 1,
        "sets": [{"id": "all-loaded", "name": "All Loaded References"}],
        "active_set_id": "all-loaded",
    }), encoding="utf-8")
    service = SetCatalogService(path)

    status = service.configure(
        mode="manual",
        set_id="me05",
        set_name="Pitch Black",
        language="English",
        provider="tcgdex",
    )

    assert status["locked"] is True
    assert service.candidate_allowed({
        "set_id": "me05", "set_name": "Pitch Black", "language": "English"
    }) is True
    assert service.candidate_allowed({
        "set_id": "sv08", "set_name": "Surging Sparks", "language": "English"
    }) is False
    assert SetCatalogService(path).status()["active_set"]["name"] == "Pitch Black"


def test_auto_mode_allows_every_set(tmp_path):
    path = tmp_path / "sets.json"
    path.write_text(json.dumps({"version": 1, "sets": []}), encoding="utf-8")
    service = SetCatalogService(path)
    service.configure(mode="auto")
    assert service.candidate_allowed({"set_id": "anything"}) is True


def test_set_context_controls_and_routes_exist():
    control = open("rareiq/web/static/control.html", encoding="utf-8").read()
    script = open("rareiq/web/static/studiox.js", encoding="utf-8").read()
    server = open("rareiq/web/server.py", encoding="utf-8").read()
    for marker in (
        "setContextMode", "setContextSelect", "scanPackSetButton", "learnPackSetButton",
        "packRecognitionPanel", "packRecognitionSet", "packRecognitionConfidence", "packAutoDetect", "packAutoAdvance", "packAutoNext",
        "packStartCardsButton", "nextPackSessionButton", "packExpectedCards", "packRareSlot", "packProfileSuggestion", "packProfileApplySuggestion",
        "packSessionProgress", "packSessionPackLabel", "packSessionCardCount", "packSessionProgressFill", "packSessionRareMarker", "packSessionRareStatus",
    ):
        assert marker in control
    assert "/api/recognition/set-context" in script
    assert "/api/recognition/scan-pack" in script
    assert "/api/recognition/learn-pack" in script
    assert "STUDIOX_SET_MODE_KEY" in script
    assert "STUDIOX_PACK_AUTO_DETECT_KEY" in script
    assert "schedulePackAutoDetect" in script
    assert "runPackAutoDetect" in script
    assert "STUDIOX_PACK_AUTO_ADVANCE_KEY" in script
    assert "packAutoAdvanceEnabled" in script
    assert "startCardsFromPack(true)" in script
    assert "STUDIOX_PACK_AUTO_NEXT_KEY" in script
    assert "packAutoNextEnabled" in script
    assert "Returning to wrapper detection" in script
    assert "loadPackArtworkIndex" in script
    assert "startCardsFromPack" in script
    assert 'mode:"manual",set_id:match.set_id' in script
    assert 'await requestNextRecognition()' in script
    assert 'document.body.dataset.packSession=active?"active":""' in script
    assert "STUDIOX_PACK_SESSION_KEY" in script
    assert "advancePackSessionCard" in script
    assert "packSessionProgressState" in script
    assert "Rare slot expected at card" in script
    assert "Hit evidence recorded at card" in script
    assert "last_confirmed_position:Number(revealState?.position||0)" in script
    assert "rare_slot:Number(revealState?.rare_slot||profile.rareSlot)" in script
    assert "startNextPackSession" in script
    assert "activePackWorkflowStatus" in script
    assert "activePackMatch" in script
    assert 'localStorage.setItem(STUDIOX_SET_MODE_KEY,"pack")' in script
    assert 'sessionStorage.setItem(STUDIOX_WORKFLOW_SESSION_KEY,"pack")' in script
    assert "STUDIOX_PACK_PROFILES_KEY" in script
    assert "packProfileFor" in script
    assert "expected_cards:profile.expectedCards,rare_slot:profile.rareSlot" in script
    assert "/api/recognition/pack-profile" in script
    assert '@app.post("/api/recognition/pack-profile")' in server
    assert '/api/recognition/pack-profile/observe' in script
    assert '@app.post("/api/recognition/pack-profile/observe")' in server
    assert 'api("/api/creator/reveal-sequence/next-pack"' in script
    assert 'advancePackSessionCard(result.reveal_sequence)' in script
    assert "const authoritative=Boolean(payload.status?.locked)" in script
    assert '@app.post("/api/recognition/set-context")' in server
    assert '@app.post("/api/recognition/scan-pack")' in server
    assert '@app.post("/api/recognition/learn-pack")' in server
    assert '@app.get("/api/recognition/pack-index")' in server
    assert '@app.get("/api/recognition/pack-reference/{reference_id}")' in server
    assert "set_options" in server


def test_pack_workspace_exposes_a_clear_wrapper_to_card_operator_flow():
    control = open("rareiq/web/static/control.html", encoding="utf-8").read()
    script = open("rareiq/web/static/studiox.js", encoding="utf-8").read()
    styles = open("rareiq/web/static/studiox_update15.css", encoding="utf-8").read()

    assert 'id="packWorkflowRail" aria-label="Pack scanning workflow"' in control
    for step in ("mode", "wrapper", "set", "cards"):
        assert f'data-pack-step="{step}"' in control
    assert 'id="packReturnToCardsButton" type="button">Card Identify<' in control
    assert 'aria-label="Pack workflow automation"' in control
    assert 'role="status" aria-live="polite"' in control

    assert "function renderPackWorkflowRail" in script
    assert 'wrapper:found?["complete","Recognized"]:["active","Show or learn"]' in script
    assert 'progress.complete?`${progress.size}/${progress.size} complete`:`${progress.confirmed}/${progress.size} cards`' in script
    assert 'const recognition=setMode==="pack"?"Pack Scan":recognitionMode' in script
    assert '$("packReturnToCardsButton")?.addEventListener("click",()=>chooseRecognitionWorkflow("identify")' in script
    assert 'found&&locked?"Start Scanning Cards":"Waiting for Set Lock"' in script
    assert '$("packStartCardsButton").disabled=Boolean(progress)||!(found&&locked)' in script
    assert "function handleRecognitionSetModeChange" in script
    assert '$("recognitionWorkflowPrompt").hidden=true' in script

    assert ".pack-workflow-rail" in styles
    assert '.pack-workflow-rail li[data-state="active"]' in styles
    assert ".pack-recognition-header-actions" in styles
    assert "#packReturnToCardsButton" in styles


def test_pack_wrapper_learning_reuses_existing_scan_and_learn_contracts():
    control = open("rareiq/web/static/control.html", encoding="utf-8").read()
    script = open("rareiq/web/static/studiox.js", encoding="utf-8").read()
    styles = open("rareiq/web/static/studiox_update15.css", encoding="utf-8").read()

    for marker in (
        'id="packWrapperCoach"',
        'id="packChooseSetButton"',
        'id="packScanWrapperButton"',
        'id="packLearnWrapperButton"',
        "Save Current Wrapper",
    ):
        assert marker in control

    assert "function renderPackLearningCoach" in script
    assert 'renderPackLearningCoach({match:found?match:null,locked})' in script
    assert '$("packChooseSetButton")?.addEventListener("click"' in script
    assert '$("packScanWrapperButton")?.addEventListener("click",()=>scanPackSet(false))' in script
    assert '$("packLearnWrapperButton")?.addEventListener("click",learnPackSet)' in script
    assert '"Add Wrapper View":"Save Current Wrapper"' in script
    assert "Set confirmed" in script
    assert "/api/recognition/scan-pack" in script
    assert "/api/recognition/learn-pack" in script

    assert ".pack-wrapper-coach" in styles
    assert '.pack-wrapper-coach[data-state="verifying"]' in styles
    assert '.pack-wrapper-coach[data-state="saved"]' in styles
    assert '.pack-wrapper-coach[data-state="error"]' in styles


def test_pack_session_progress_tracks_cards_rare_slot_and_completion():
    control = open("rareiq/web/static/control.html", encoding="utf-8").read()
    script = open("rareiq/web/static/studiox.js", encoding="utf-8").read()
    styles = open("rareiq/web/static/studiox_update15.css", encoding="utf-8").read()

    assert 'id="packSessionProgress"' in control
    assert 'role="status" aria-live="polite" aria-label="Pack session progress"' in control
    for marker in (
        'id="packSessionPackLabel"',
        'id="packSessionCardCount"',
        'id="packSessionProgressFill"',
        'id="packSessionRareMarker"',
        'id="packSessionRareStatus"',
    ):
        assert marker in control

    assert "function packSessionProgressState(session)" in script
    assert 'progress:complete?100:Math.round(confirmed/size*100)' in script
    assert 'card===rareSlot' in script
    assert 'observedRareSlot' in script
    assert 'progress.dataset.state=complete?"complete":state.card===state.rareSlot?"rare":"active"' in script
    assert 'setCardText("packSessionCardCount",complete?' in script
    assert 'setCardText("packSessionRareStatus",state.rareStatus)' in script
    assert 'last_confirmed_position:Number(revealState?.position||0)' in script
    assert 'rare_slot:Number(revealState?.rare_slot||profile.rareSlot)' in script
    assert 'renderPackRecognition(activePackMatch(),true)' in script
    assert 'progress?.complete?"Pack Complete":progress?`Card ${progress.card} of ${progress.size}`' in script

    assert ".pack-session-progress" in styles
    assert '.pack-session-progress[data-state="rare"]' in styles
    assert '.pack-session-progress[data-state="complete"]' in styles
    assert '.pack-session-progress-track>em' in styles
