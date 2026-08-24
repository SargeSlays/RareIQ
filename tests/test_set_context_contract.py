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
    assert "startNextPackSession" in script
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
