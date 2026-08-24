from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "rareiq" / "web" / "static"
HTML = (STATIC / "control.html").read_text(encoding="utf-8")
JS = (STATIC / "studiox.js").read_text(encoding="utf-8")
CSS = (STATIC / "studiox_update15.css").read_text(encoding="utf-8")


def test_command_bar_has_four_normal_flow_groups() -> None:
    toolbar = HTML[HTML.index('class="toolbar premium-command-bar'):HTML.index('<main class="workspace-stage">')]
    for marker in (
        "premium-source-control",
        "studiox-layout-control",
        "premium-view-control",
        "premium-actions-control",
    ):
        assert toolbar.count(marker) == 1
    cleanup = CSS[CSS.index("/* Surgical UI cleanup") :]
    assert "grid-template-columns:" in cleanup
    compact_start = cleanup.index(
        "body.studiox-ui4.studiox-premium .camera-source-compact-menu{"
    )
    command_menu = cleanup[compact_start:cleanup.index("}", compact_start)]
    assert "position:absolute" not in command_menu
    assert "margin:-" not in command_menu


def test_viewer_controls_and_handlers_are_preserved_once() -> None:
    for element_id in (
        "viewerModeSelect",
        "viewerZoomOut",
        "viewerZoomReset",
        "viewerZoomIn",
        "cameraFitToggle",
        "cameraZoomToggle",
        "autoCaptureToggle",
    ):
        assert HTML.count(f'id="{element_id}"') == 1
    assert '$("viewerZoomOut")?.addEventListener("click"' in JS
    assert '$("viewerZoomReset")?.addEventListener("click"' in JS
    assert '$("viewerZoomIn")?.addEventListener("click"' in JS


def test_viewer_zoom_controls_reflect_real_bounds_and_fit_state() -> None:
    assert "const STUDIOX_PREVIEW_ZOOM_MIN=.8;" in JS
    assert "const STUDIOX_PREVIEW_ZOOM_MAX=2.5;" in JS
    assert "const STUDIOX_PREVIEW_ZOOM_STEP=.1;" in JS
    start = JS.index("function syncStudioXViewerZoomControls")
    end = JS.index("function setStudioXViewerMode", start)
    zoom_controls = JS[start:end]
    assert '$("viewerZoomOut").disabled=atMinimum' in zoom_controls
    assert '$("viewerZoomIn").disabled=atMaximum' in zoom_controls
    assert '$("viewerZoomReset").disabled=atFit' in zoom_controls
    assert "Number((studioXPreferences.previewZoom+delta).toFixed(2))" in JS


def test_confidence_sources_are_labeled_separately() -> None:
    assert "Recognition confidence" in HTML
    assert '<span>Visual confidence</span><b id="identifyVisualConfidence">' in HTML
    assert '"identifyCatalogStatus"' in JS
    assert '?"Exact"' in JS


def test_provisional_is_a_badge_not_card_metadata() -> None:
    assert 'id="identityVerdictBadge"' in HTML
    assert 'id="identityVerdictBadge" aria-hidden="true" hidden' in HTML
    assert '"Candidate only  |  Exact version unresolved"' in JS
    assert '"WAITING FOR VERIFIED IDENTITY"' in JS
    assert 'badge.textContent=verified?"EXACT MATCH":"CANDIDATE · VERIFYING"' in JS


def test_sticky_actions_and_polished_empty_states() -> None:
    cleanup = CSS[CSS.index("/* Surgical UI cleanup") :]
    assert ".inspector-actions" in cleanup
    assert "position:sticky" in cleanup
    assert ".inspector-command-strip" in cleanup
    assert "grid-template-columns:minmax(0,1.28fr) minmax(0,.82fr) minmax(0,1fr)" in cleanup
    assert "AI Grade is unavailable because no grading provider is connected." in JS
    assert "No verified market data is available for this card." in JS
    assert "Exact identity verified. No alternative candidates require review." in JS


def test_scrollbar_preview_and_id_integrity_contracts() -> None:
    cleanup = CSS[CSS.index("/* Surgical UI cleanup") :]
    assert "scrollbar-width:thin" in cleanup
    assert "::-webkit-scrollbar-thumb" in cleanup
    assert "aspect-ratio:16/9" in cleanup
    assert "object-fit:contain" in cleanup
    ids = re.findall(r'\bid="([^"]+)"', HTML)
    assert len(ids) == len(set(ids))
