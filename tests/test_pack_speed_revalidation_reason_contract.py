from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")


def test_revalidation_reason_names_each_supported_configuration_field():
    labels = JS.split("const PACK_TUNING_CONFIGURATION_LABELS", 1)[1].split("function parsePackTuningFingerprint", 1)[0]
    for label in ("Camera source", "Workspace", "Recognition mode", "Set mode", "Selected set", "Viewer mode"):
        assert label in labels


def test_freshness_reports_changed_fields_or_exact_age():
    freshness = JS.split("function packBestTuningFreshness", 1)[1].split("function packBestTuningConfidence", 1)[0]
    assert "changedFields" in freshness
    assert "changedLabels.join" in freshness
    assert "Revalidate after changing:" in freshness
    assert "days old" in freshness


def test_reason_is_visible_only_for_stale_profiles_and_build_is_current():
    render = JS.split("function renderPackTuningHistory", 1)[1].split("function renderPackSessionHealth", 1)[0]
    assert 'id="packBestTuningFreshnessReason"' in render
    assert "reasonNode.hidden=!best||freshness.fresh" in render
    assert "#packBestTuningFreshnessReason" in CSS
    assert "6.8.8-provisional-identity" in HTML
