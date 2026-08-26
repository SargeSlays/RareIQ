from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")


def test_verified_current_card_is_authoritative_in_live_ui():
    load = SCRIPT.split("async function loadRecognition", 1)[1]
    assert "result?.current_card" in load
    assert "canonicalVerified" in load
    assert "canonicalCard ||" in load
    assert "collectorOcrEvidence" in load


def test_rare_intelligence_uses_verified_canonical_card():
    endpoint = SERVER.split("async def current_pokedex_entry", 1)[1]
    endpoint = endpoint.split("@app.post(\"/api/pokedex/on-air\"", 1)[0]
    assert "normalize_current_card" in endpoint
    assert '"name": canonical.get("card_name")' in endpoint
    assert "profile_verified = True" in endpoint
    assert "RareIQOrchestrator._identity_is_authoritative(current)" in endpoint
    assert '"on_air": bool(overlay.get("pokedex_on_air")) and profile_verified' in endpoint
    assert '"broadcast_eligible": profile_verified' in endpoint
    assert 'for current_candidate in current.get("candidates") or []:' in endpoint
    assert "profile_verified = False" in endpoint


def test_live_api_only_publishes_authoritative_current_card():
    endpoint = SERVER.split("async def recognition_state", 1)[1]
    endpoint = endpoint.split('@app.get("/api/tcg/games")', 1)[0]
    assert "authoritative_current_card" in endpoint

    service = (
        ROOT / "rareiq" / "services" / "backend_test_service.py"
    ).read_text(encoding="utf-8")
    runtime = service.split("def runtime_snapshot", 1)[1]
    runtime = runtime.split("def smoke_test", 1)[0]
    assert '"current_card": self.authoritative_current_card(' in runtime


def test_legacy_overlay_state_cannot_accept_a_candidate_as_current_card():
    endpoint = SERVER.split("async def update_overlay_state", 1)[1]
    endpoint = endpoint.split('@app.post("/api/overlay/reset")', 1)[0]
    assert 'state.pop("current_card", None)' in endpoint
    assert '"state": _broadcast_overlay_state()' in endpoint

    overlay = (
        ROOT / "rareiq" / "web" / "static" / "overlay_v3.js"
    ).read_text(encoding="utf-8")
    assert 'state.current_card_status==="verified"' in overlay


def test_latency_total_cannot_be_less_than_visible_stages():
    renderer = SCRIPT.split("function renderRecognitionLatencyTrace", 1)[1]
    renderer = renderer.split("function loadRecognitionLatencySamples", 1)[0]
    assert "measuredStages" in renderer
    assert "Math.max(" in renderer
