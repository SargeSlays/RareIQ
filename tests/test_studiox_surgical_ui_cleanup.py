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
    assert "position:absolute" not in cleanup
    assert "margin:-" not in cleanup


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


def test_confidence_sources_are_labeled_separately() -> None:
    assert "Recognition confidence" in HTML
    assert '<span>Visual confidence</span><b id="identifyVisualConfidence">' in HTML
    assert '"identifyCatalogStatus"' in JS
    assert '?"Exact"' in JS


def test_provisional_is_a_badge_not_card_metadata() -> None:
    assert 'id="identityVerdictBadge" hidden' in HTML
    metadata = JS[JS.index('$("cardMeta").textContent = ['):JS.index("renderIdentityVerdictBadge", JS.index('$("cardMeta").textContent = ['))]
    assert "PROVISIONAL" not in metadata
    assert 'badge.textContent=verified?"EXACT MATCH":"PROVISIONAL"' in JS


def test_sticky_actions_and_polished_empty_states() -> None:
    cleanup = CSS[CSS.index("/* Surgical UI cleanup") :]
    assert ".inspector-actions" in cleanup
    assert "position:sticky" in cleanup
    assert "#approveButton{grid-column:1}" in cleanup
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
