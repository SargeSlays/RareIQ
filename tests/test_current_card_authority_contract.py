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


def test_latency_total_cannot_be_less_than_visible_stages():
    renderer = SCRIPT.split("function renderRecognitionLatencyTrace", 1)[1]
    renderer = renderer.split("function loadRecognitionLatencySamples", 1)[0]
    assert "measuredStages" in renderer
    assert "Math.max(" in renderer
