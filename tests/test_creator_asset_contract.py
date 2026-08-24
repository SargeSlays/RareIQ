from pathlib import Path

SERVER = Path("rareiq/web/server.py").read_text(encoding="utf-8")
CONTROL = Path("rareiq/web/static/control.html").read_text(encoding="utf-8")
STUDIO = Path("rareiq/web/static/studiox.js").read_text(encoding="utf-8")
OVERLAY = Path("rareiq/web/static/overlay_reveal_sequence.html").read_text(encoding="utf-8")

def test_creator_asset_routes_and_controls_exist():
    assert '@app.post("/api/creator/assets")' in SERVER
    assert '@app.post("/api/creator/assets/map")' in SERVER
    assert 'id="creatorAssetUpload"' in CONTROL
    assert 'id="creatorTierMapping"' in CONTROL
    assert "function renderCreatorAssets(payload={})" in STUDIO

def test_reveal_source_uses_only_explicit_mapped_assets():
    assert 'state["reaction_assets"]' in SERVER
    assert 's.audio_enabled===true' in OVERLAY
    assert 'mapped.visual?.url' in OVERLAY
    assert 'mapped.audio?.url' in OVERLAY
