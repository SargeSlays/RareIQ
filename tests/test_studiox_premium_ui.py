from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "rareiq" / "web" / "static"


def read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8-sig")


def test_premium_shell_and_toolbar_contract() -> None:
    html = read("control.html")
    css = read("studiox_update15.css")
    assert "studiox-premium" in html
    for marker in (
        "premium-source-control", "studiox-layout-control",
        "premium-view-control", "premium-actions-control", "premium-capture-action",
        "premium-more-menu", "unifiedScanStatus",
    ):
        assert marker in html
    assert "@media(min-width:960px)" in css
    assert "grid-template-columns:72px minmax(0,1fr)" in css
    assert "overflow:hidden" in css


def test_truthful_collector_number_contract() -> None:
    html = read("control.html")
    script = read("studiox.js")
    assert "<span>Local Card ID</span>" in html
    assert 'id="officialNumberField" hidden' in html
    assert 'id="cardOfficialNumber"' in html
    assert '"official_collector_number"' in script
    assert "officialField.hidden=!officialNumber" in script


def test_explicit_recognition_and_market_states() -> None:
    script = read("studiox.js")
    assert "function deriveRecognitionPresentation" in script
    for state in (
        "ready", "scanning", "candidate-found", "verifying", "exact-match",
        "review-needed", "error",
    ):
        assert f'key:"{state}"' in script
    assert "function deriveMarketPresentation" in script
    for state in ("pending", "available", "no-data", "provider-error"):
        assert f'key:"{state}"' in script


def test_initialization_and_tabs_are_stable_and_accessible() -> None:
    html = read("control.html")
    script = read("studiox.js")
    assert 'dataset.ui4Initialized==="true"' in script
    assert 'dataset.ui4Initialized="true"' in script
    assert "document.createElement(\"section\")" not in script[
        script.index("function initializeStudioXUI4"):
        script.index('document.addEventListener("DOMContentLoaded"')
    ]
    assert html.count("data-studiox-widget=") == 11
    assert 'data-widget-visibility="identify"' in html
    assert "applyStudioXWidgetLayout()" in script


def test_handlers_and_reduced_motion_remain() -> None:
    html = read("control.html")
    css = read("studiox_update15.css")
    for handler in (
        "selectCamera()", "startSelectedCamera()", "stopCamera()",
        "captureCamera()", "toggleAutoCapture()", "openCameraPopout()",
        "cycleCameraFit()", "toggleCardZoom()", "operatorApprove()",
        "operatorReject()", "operatorDetails()", "openProgram()",
    ):
        assert handler in html
    for handler in ("loadCameraList", "reconnectCamera", "restartFeed"):
        assert handler in read("studiox.js")
    assert "@media(prefers-reduced-motion:reduce)" in css
    assert "animation-duration:.01ms!important" in css


def test_no_duplicate_ids() -> None:
    ids = re.findall(r'\bid="([^"]+)"', read("control.html"))
    assert len(ids) == len(set(ids))


def test_recognition_copy_uses_one_authoritative_presentation() -> None:
    html = read("control.html")
    script = read("studiox.js")
    apply_start = script.index("function applyRecognitionPresentation")
    apply_end = script.index("function setRecognitionState", apply_start)
    apply_block = script[apply_start:apply_end]
    load_start = script.index("async function loadRecognition")
    load_end = script.index("async function loadSystemHealth", load_start)
    load_block = script[load_start:load_end]

    assert "applyRecognitionPresentation(presentation)" in load_block
    assert '$("aiState").textContent=title' in apply_block
    assert '$("cardPlaceholderTitle").textContent=' in apply_block
    assert 'setStateChip("aiStateChip",aiChipState,title)' in apply_block
    assert "setCoreState(key)" in apply_block
    assert '$("cardStatus").textContent=presentation.title' in load_block
    assert '$("aiState").textContent=presentation.title' not in load_block
    assert "Waiting for Card" not in html


def test_recognition_states_cannot_render_contradictory_copy() -> None:
    script = read("studiox.js")
    derive_start = script.index("function deriveRecognitionPresentation")
    derive_end = script.index("async function loadRecognition", derive_start)
    derive = script[derive_start:derive_end]

    for state in (
        "ready", "scanning", "candidate-found", "verifying",
        "exact-match", "review-needed", "error",
    ):
        assert f'key:"{state}"' in derive
    assert 'snapshot?.card_present===true' in derive
    assert '"SEARCHING"' not in derive


def test_native_4k_contract_preserves_smaller_breakpoints() -> None:
    css = read("studiox_update15.css")
    assert "@media(min-width:1900px) and (min-height:1000px)" in css
    assert "@media(min-width:3000px) and (min-height:1600px)" in css
    assert "--premium-result-width:620px" in css
    assert "--premium-rail-width:128px" in css
    assert ".ui4-desktop-shell{transform:scale(" not in css.replace(" ", "")
    assert "@media(min-width:960px) and (max-width:1180px)" in css
    assert "grid-template-columns:60px minmax(0,1fr) 350px" in css


def test_multiple_widgets_are_simultaneous_and_independent() -> None:
    html = read("control.html")
    script = read("studiox.js")
    for widget in (
        "identify", "ai-grade", "market",
        "candidates", "details", "diagnostics",
    ):
        assert f'data-studiox-widget="{widget}"' in html
    assert "panel.hidden=panel.dataset.premiumPanel!==selected" not in script
    assert "widget.classList.toggle(" in script
    assert '"is-collapsed"' in script
    assert 'node.classList.toggle("is-focused",node===widget)' in script
    assert "studioXWidgetLayout.collapsed" in script


def test_shared_card_context_updates_widgets_with_error_isolation() -> None:
    script = read("studiox.js")
    assert "function deriveSharedCardContext" in script
    assert "function updateSharedCardContext" in script
    assert "window.__rareiqCardContext=context" in script
    for renderer in (
        "renderIdentifyWidget", "renderAIGradeWidget", "renderMarketWidget",
        "renderCandidatesWidget", "renderDetailsWidget",
        "renderDiagnosticsWidget",
    ):
        assert renderer in script
    update_start = script.index("function updateSharedCardContext")
    update_end = script.index("function initializeStudioXUI4", update_start)
    update = script[update_start:update_end]
    assert "Object.entries(STUDIOX_WIDGET_RENDERERS).forEach" in update
    assert "try{" in update
    assert 'setStudioXWidgetState(id,"error")' in update


def test_widget_layout_schema_restores_and_falls_back_safely() -> None:
    script = read("studiox.js")
    assert 'STUDIOX_WIDGET_LAYOUT_KEY="rareiq.studiox.widgetLayout.v2"' in script
    assert 'STUDIOX_WIDGET_LAYOUT_LEGACY_KEY="rareiq.studiox.widgetLayout.v1"' in script
    for field in ("version:2", "order:", "hidden:", "collapsed:", "pinned:", "sizes:"):
        assert field in script
    assert "function normalizeStudioXWidgetLayout" in script
    assert "![1,2].includes(value.version)" in script
    assert "savedV2||savedV1" in script
    assert "JSON.stringify(studioXWidgetLayout)" in script
    assert "function resetStudioXWidgetLayout" in script


def test_ai_grade_shell_never_invents_scores() -> None:
    html = read("control.html")
    script = read("studiox.js")
    assert "Estimated AI condition analysis" in html
    assert "not an official grading-company grade" in html
    for state in (
        "unavailable", "waiting-for-stable-capture",
        "front-analysis-ready", "back-image-required",
        "analyzing", "error",
    ):
        assert f'"{state}"' in script
    for row in (
        "aiGradeCentering", "aiGradeCorners", "aiGradeEdges",
        "aiGradeSurface", "aiGradeRange", "aiGradeConfidence",
    ):
        assert f'id="{row}"' in html
    assert html.count(">Pending</b>") >= 6


def test_workspace_presets_are_studiox_only_and_persist_safely() -> None:
    html = read("control.html")
    script = read("studiox.js")
    css = read("studiox_update15.css")
    assert 'id="workspaceLayoutPreset"' in html
    for preset in ("intelligence", "balanced", "monitor"):
        assert f'value="{preset}"' in html
        assert f'data-workspace-preset="{preset}"' in css
    for label in ("Info Focus", "Balanced", "Camera Focus", "Custom Split"):
        assert f">{label}</option>" in html
    assert 'STUDIOX_PREFERENCES_KEY="rareiq.studiox.workspacePreferences.v1"' in script
    assert 'layoutPreset:"intelligence"' in script
    assert "function normalizeStudioXPreferences" in script
    assert "function applyWorkspaceLayoutPreset" in script
    assert 'document.body.dataset.workspacePreset=' in script
    assert "function announceWorkspaceLayoutPreset" in script
    assert 'notify("Workspace Updated"' in script
    assert 'document.body.dataset.ui4Workspace==="live"' in script
    for shortcut in ("ALT + 1", "ALT + 2", "ALT + 3"):
        assert f"<kbd>{shortcut}</kbd>" in html
    preset_start = script.index("function applyWorkspaceLayoutPreset")
    preset_end = script.index("function normalizedCardFocusGeometry", preset_start)
    assert "openProgram" not in script[preset_start:preset_end]


def test_inspector_section_jump_navigation_is_available() -> None:
    html = read("control.html")
    script = read("studiox.js")
    assert 'id="inspectorSectionNav"' in html
    for target in ("cardContextHeader", "recognitionSignalPanel", "widgetWorkspace"):
        assert f'data-inspector-section="{target}"' in html
    assert 'currentView.scrollTo({' in script


def test_viewer_modes_use_existing_geometry_and_fall_back_truthfully() -> None:
    html = read("control.html")
    script = read("studiox.js")
    for mode in ("auto", "full-frame", "card-focus"):
        assert f'value="{mode}"' in html
    assert "function normalizedCardFocusGeometry" in script
    assert "vision?.scan_zone" in script
    assert "vision?.card_corners" in script
    assert "context?.verified" in script
    assert 'context?.presentation?.key==="exact-match"' in script
    assert 'requested==="card-focus"&&!geometry' in script
    assert "Card focus unavailable" in script
    assert 'effectiveMode=focusAvailable?"card-focus":"full-frame"' in script


def test_preview_zoom_is_clamped_resettable_and_preview_only() -> None:
    html = read("control.html")
    script = read("studiox.js")
    assert 'id="viewerZoomOut"' in html
    assert 'id="viewerZoomReset"' in html
    assert 'id="viewerZoomIn"' in html
    assert "Math.max(STUDIOX_PREVIEW_ZOOM_MIN,Math.min(STUDIOX_PREVIEW_ZOOM_MAX,zoom))" in script
    assert "const STUDIOX_PREVIEW_ZOOM_MIN=.8;" in script
    assert "const STUDIOX_PREVIEW_ZOOM_MAX=2.5;" in script
    assert "function resetStudioXPreviewZoom" in script
    viewer_start = script.index("function applyStudioXViewerPresentation")
    viewer_end = script.index("function setStudioXViewerMode", viewer_start)
    viewer = script[viewer_start:viewer_end]
    assert "--studiox-preview-scale" in viewer
    assert "/api/camera/capture" not in viewer
    assert "recognition" not in viewer.lower()
    assert "openProgram" not in viewer


def test_widget_size_contract_and_v1_migration() -> None:
    script = read("studiox.js")
    css = read("studiox_update15.css")
    for size in ("compact", "standard", "wide"):
        assert f'"{size}"' in script
        assert f'data-widget-size="{size}"' in css
    assert "value.version===2" in script
    assert "value.version===1" not in script
    assert "sizes={...STUDIOX_DEFAULT_WIDGET_LAYOUT.sizes}" in script
    assert 'data-widget-action="size"' in script


def test_empty_states_hide_unavailable_metric_grids_and_no_fake_claims() -> None:
    html = read("control.html")
    script = read("studiox.js")
    combined = f"{html}\n{script}"
    assert 'id="aiGradeMetrics" hidden' in html
    assert "gradeMetrics.hidden=" in script
    assert 'marketWidget?.querySelectorAll(".ui4-price-primary,.ui4-price-grid")' in script
    assert "node.hidden=!hasMetrics" in script
    assert "99.99%" not in combined
    assert "official grading-company grade" in html


def test_card_context_reset_clears_stale_identity_and_returns_auto_to_full_frame() -> None:
    script = read("studiox.js")
    reset_start = script.index("function resetRecognitionPresentation")
    reset_end = script.index("function deriveRecognitionPresentation", reset_start)
    reset = script[reset_start:reset_end]
    assert '$("cardArt").innerHTML=""' in reset
    assert '$("cardName").textContent="Ready to Scan"' in reset
    assert "resetExtendedCardData()" in reset
    assert "deriveSharedCardContext(" in reset
    assert "card:null" not in reset
    assert 'requested==="auto"&&stableLock' in script
