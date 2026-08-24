from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")


def test_profile_fingerprint_covers_recognition_environment():
    fingerprint = JS.split("function packTuningConfigurationFingerprint", 1)[1].split("function packBestTuningFreshness", 1)[0]
    for control in ("cameraSlot1Source", "cameraSelect", "workspaceLayoutPreset", "recognitionModeSelect", "setContextMode", "setContextSelect", "viewerModeSelect"):
        assert control in fingerprint


def test_profile_expires_or_revalidates_after_configuration_change():
    assert "PACK_BEST_TUNING_MAX_AGE_MS=30*24*60*60*1000" in JS
    freshness = JS.split("function packBestTuningFreshness", 1)[1].split("function packBestTuningConfidence", 1)[0]
    assert 'reason:"configuration-changed"' in freshness
    assert 'reason:"expired"' in freshness
    assert "ageMs>PACK_BEST_TUNING_MAX_AGE_MS" in freshness


def test_stale_profile_is_never_recommended_or_applied():
    confidence = JS.split("function packBestTuningConfidence", 1)[1].split("function updatePackBestTuning", 1)[0]
    apply = JS.split("async function applyPackBestTuning", 1)[1].split("function renderPackTuningHistory", 1)[0]
    assert "recommended:fresh&&runs>=2" in confidence
    assert "packBestTuningFreshness(profile)" in apply
    assert 'data-confidence="revalidate"' in CSS
    assert "6.8.8-provisional-identity" in HTML
