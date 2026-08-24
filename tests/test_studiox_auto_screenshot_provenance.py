import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "rareiq" / "web" / "static"


def read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_auto_screenshot_defaults_off_and_starts_disabled_until_capability_loads() -> None:
    html = read("control.html")
    script = read("studiox.js")
    assert 'id="autoScreenshotEnabled" type="checkbox" disabled' in html
    assert 'id="autoScreenshotManualCapture"' in html
    assert 'type="button" disabled>Manual Screenshot' in html
    assert "Screenshot capture engine not connected" in html
    assert "let AUTO_SCREENSHOT_BACKEND_AVAILABLE=false" in script
    assert "AUTO_SCREENSHOT_BACKEND_AVAILABLE=payload.available===true" in script
    assert "enabled:false" in script


def test_configuration_uses_one_backend_settings_request_and_no_capture_loop() -> None:
    script = read("studiox.js")
    start = script.index("function initializeAutoScreenshotConfiguration")
    section = script[start:script.index("function defaultStudioXWidgetLayout", start)]
    assert "persistAutoScreenshotSettings(config)" in section
    assert 'requestAutoScreenshotBackend("/api/provenance/settings")' in section
    assert 'requestAutoScreenshotBackend("/api/provenance/capture",{method:"POST"})' in script
    assert "/api/camera/capture" not in section
    assert "setInterval" not in section


def test_manual_handler_binds_before_the_large_shell_initializer() -> None:
    script = read("studiox.js")
    dom_ready = script.index('document.addEventListener("DOMContentLoaded",()=>{')
    early_bind = script.index("initializeAutoScreenshotConfiguration();", dom_ready)
    shell_init = script.index("initializeStudioXUI4();", dom_ready)
    assert early_bind < shell_init
    assert "autoScreenshotInitialized" in script
    initialize = script[
        script.index("async function initializeAutoScreenshotConfiguration"):
        script.index("function defaultStudioXWidgetLayout")
    ]
    assert initialize.index('addEventListener("click",manualAutoScreenshotCapture)') < initialize.index(
        'requestAutoScreenshotBackend("/api/provenance/settings")'
    )


def test_trigger_safety_requires_authoritative_evidence() -> None:
    script = read("studiox.js")
    start = script.index("function autoScreenshotTriggerQualifies")
    end = script.index("function buildAutoScreenshotProvenanceEvent", start)
    trigger = script[start:end]
    assert 'verdict==="exact-match"' in trigger
    assert "options.truthfulRarity" in trigger
    assert "Number.isFinite(options.truthfulMarketValue)" in trigger
    assert "options.qualifyingHit===true" in trigger
    assert "!AUTO_SCREENSHOT_BACKEND_AVAILABLE||!value.enabled" in trigger


def test_proof_record_requires_backend_confirmation() -> None:
    script = read("studiox.js")
    start = script.index("function buildAutoScreenshotProvenanceEvent")
    end = script.index("function createAutoScreenshotCorrectionRevision", start)
    builder = script[start:end]
    assert "!confirmation?.ok" in builder
    assert "!confirmation.eventId" in builder
    assert "!confirmation.capturedAt" in builder
    assert "Backend confirmation is required" in builder
    assert "confirmation.assets?.fullFrame" in builder
    assert "confirmation.assets?.cardFocus" in builder
    assert "confirmation.assets?.evidenceView" in builder


def test_pack_and_battle_fields_persist_and_normalize() -> None:
    html = read("control.html")
    script = read("studiox.js")
    for value in ("single-card-sales", "pack-ripping", "pack-battle"):
        assert f'value="{value}"' in html
    for value in ("player-1", "player-2"):
        assert f'value="{value}"' in html
    assert "packNumber:normalizedPositiveInteger(value.packNumber)" in script
    assert "turnNumber:normalizedPositiveInteger(value.turnNumber)" in script
    assert 'workflowMode==="pack-battle"' in script
    assert "AUTO_SCREENSHOT_CONFIG_KEY" in script


def test_capture_types_and_geometry_truth_are_documented() -> None:
    html = read("control.html")
    requirements = (ROOT / "docs" / "auto_screenshot_backend_requirements.md").read_text(
        encoding="utf-8"
    )
    for element_id in (
        "autoScreenshotFullFrame",
        "autoScreenshotCardFocus",
        "autoScreenshotEvidenceView",
    ):
        assert f'id="{element_id}"' in html
    assert "Card Focus only from validated, stable card geometry" in requirements
    assert "untouched full camera frame" in requirements


def test_correction_is_revisioned_not_silently_replaced() -> None:
    script = read("studiox.js")
    start = script.index("function createAutoScreenshotCorrectionRevision")
    end = script.index("function readAutoScreenshotForm", start)
    revision = script[start:end]
    assert "originalEventId:String(originalEvent.eventId)" in revision
    assert "revisionId:String(confirmation.revisionId)" in revision
    assert "Object.freeze" in revision


def test_cache_version_and_widget_contract() -> None:
    html = read("control.html")
    script = read("studiox.js")
    assert html.count('data-studiox-widget="auto-screenshot"') == 1
    assert 'data-widget-visibility="auto-screenshot"' in html
    assert '"auto-screenshot":"Auto Screenshot"' in script
    version = re.search(r'data-studiox-build="([^"]+)"', html).group(1)
    assert f"/static/studiox.js?v={version}" in html
    assert f"/static/studiox_update15.css?v={version}" in html
