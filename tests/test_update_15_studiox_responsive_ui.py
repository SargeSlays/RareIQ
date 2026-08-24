from __future__ import annotations

import hashlib
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "rareiq" / "web" / "static"


def read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8-sig")


def test_live_camera_header_controls_accept_pointer_input() -> None:
    css = read("studiox_update15.css")
    rules = re.findall(
        r"body\.studiox-ui4\.studiox-premium \.viewer-inspection-header\s*\{([^}]+)\}",
        css,
    )
    assert rules
    assert any("pointer-events:auto" in rule for rule in rules)


def test_all_existing_ids_remain_unique() -> None:
    html = read("control.html")
    ids = re.findall(r'\bid="([^"]+)"', html)
    assert len(ids) == len(set(ids))
    for required in (
        "cameraFeed", "inspectorMain", "cardArt", "cardEnglishName",
        "cardCollectorNumber", "cardOfficialNumber", "approveButton",
    ):
        assert required in ids


def test_one_camera_feed_and_no_video_clone() -> None:
    html = read("control.html")
    assert html.count('id="cameraFeed"') == 1
    assert len(re.findall(r'<img[^>]+id="cameraFeed"', html)) == 1
    assert "<video" not in html.lower()
    assert html.count("/api/camera/stream") == 0


def test_ui4_scope_and_semantic_regions_exist_without_new_functional_ids() -> None:
    html = read("control.html")
    assert '<body class="studiox-ui4 studiox-premium" data-ui4-region="application-shell"' in html
    for region in (
        "top-app-bar", "controls", "camera", "current-card", "pipeline",
        "diagnostics", "product-navigation", "mobile-actions",
    ):
        assert f'data-ui4-region="{region}"' in html
    assert 'class="ui4-mobile-action-region"' in html
    assert 'class="studiox-ui4 studiox-premium"' in html
    assert 'class="app-actions ui4-app-health"' in html
    assert 'class="command-group premium-source-control"' in html


def test_structural_desktop_shell_has_rail_center_and_result_columns() -> None:
    html = read("control.html")
    script = read("studiox.js")
    css = read("studiox_update15.css")
    assert html.count('class="ui4-desktop-shell"') == 1
    assert html.count('class="ui4-navigation-rail ui4-product-navigation"') == 1
    assert html.count('class="ui4-command-bar"') == 1
    assert html.count('class="ui4-inspector-column"') == 1
    assert 'class="bottom-nav' not in html
    assert "grid-template-columns:84px minmax(0,1fr) 400px" in css
    assert "grid-template-columns:188px minmax(0,1fr) 460px" in css
    assert 'inspectorMount.appendChild(inspector)' in script


def test_navigation_pipeline_drawer_and_inspector_tabs_are_single_instance() -> None:
    html = read("control.html")
    script = read("studiox.js")
    for tab in ("Thinking", "Candidates", "OCR", "Session", "Telemetry", "Recent Pulls", "Activity"):
        assert f'>{tab}</button>' in html
    assert html.count('class="nav-button') == 11
    assert 'data-target="soundboard"' in html
    assert html.count('data-panel=') == 7
    assert 'camera.appendChild(pipeline)' in script
    assert 'dock.classList.add("ui4-diagnostics-drawer")' in script
    assert 'camera.appendChild(dock)' in script
    for key in ("identify", "ai-grade", "market", "candidates", "details", "diagnostics"):
        assert f'data-studiox-widget="{key}"' in html
    assert "function setPremiumIntelligenceTab" in script


def test_presentation_helpers_use_only_expected_apis() -> None:
    script = read("studiox.js")
    start = script.index("function setUI4DiagnosticsOpen")
    end = script.index("const STUDIOX_WIDGET_LAYOUT_KEY", start)
    presentation = script[start:end]
    assert "fetch(" not in presentation
    assert presentation.count("api(") == 4
    assert "/api/intelligence/catalog-search" in presentation
    assert "/api/session/confirm-recognition-catalog-candidate" in presentation
    assert "/api/session/confirm-recognition-candidate" in presentation
    assert 'api("/api/recent-pulls?limit=20")' in presentation
    assert "loadRecognition(" not in presentation
    assert "captureCamera();" not in presentation
    assert 'setAttribute("aria-hidden"' in presentation
    assert 'resetUI4PresentationSurfaces();' in script
    assert 'event.key==="Escape"' in script


def test_existing_inline_handlers_and_keyboard_controls_remain() -> None:
    html = read("control.html")
    script = read("studiox.js")
    handlers = (
        "selectCamera()",
        "startSelectedCamera()", "stopCamera()", "captureCamera()",
        "toggleAutoCapture()", "openCameraPopout()", "cycleCameraFit()",
        "toggleCardZoom()", "operatorApprove()", "operatorReject()",
        "operatorDetails()", "toggleDock()", "openProgram()",
    )
    for handler in handlers:
        assert handler in html
    for handler in ("loadCameraList", "reconnectCamera", "restartFeed"):
        assert handler in script
    assert 'document.addEventListener("keydown",event=>' in script
    for key in ('event.key===" "', 'event.key==="Escape"', 'event.key.toLowerCase()==="a"'):
        assert key in script


def test_api_and_recognition_ordering_contracts_remain() -> None:
    script = read("studiox.js")
    endpoints = (
        "/api/camera/auto-capture", "/api/camera/start", "/api/camera/stop",
        "/api/camera/stream", "/api/camera/ready", "/api/camera/recover",
        "/api/camera/capture", "/api/camera/status", "/api/recognition-state",
        "/api/reference-image", "/api/system/health",
    )
    for endpoint in endpoints:
        assert endpoint in script
    assert "newestRecognitionGeneration=-1" in script
    assert "newestRecognitionRevision=-1" in script
    assert "generation < newestRecognitionGeneration" in script
    assert "revision < newestRecognitionRevision" in script
    assert 'hadPreviousSession ? "server_session_changed"' in script
    assert 'resetRecognitionPresentation("backend_empty")' in script
    assert 'renderPipeline([],false)' in script
    assert '$("cardArt").innerHTML=""' in script
    assert script.count("/api/camera/stream") == 3
    assert 'const source=lockedCapture?.url||"/api/camera/stream?viewer=secondary-card-focus"' in script
    assert script.count("setInterval(()=>{if(document.hidden!==true)loadRecognition()},600)") == 1


def test_ui4_stylesheets_are_cache_busted_and_last_in_cascade() -> None:
    html = read("control.html")
    styles = re.findall(r'<link rel="stylesheet" href="([^"]+)"', html)
    version = re.search(r'data-studiox-build="([^"]+)"', html).group(1)
    assert styles[-3:] == [
        f"/static/studiox_ui4_tokens.css?v={version}",
        f"/static/studiox_update15.css?v={version}&amp;shell=6.8.9-mobile-shell19",
        f"/static/pack_run_coach.css?v={version}",
    ]
    assert len(styles) == 18
    assert not any("studiox_60.css" in style for style in styles)
    assert not any("studiox_604.css" in style for style in styles)


def test_scaled_4k_keeps_diagnostics_as_an_overlay() -> None:
    css = read("studiox_update15.css")
    assert "@media(min-width:1101px)" in css
    assert ".camera-workspace>.ui4-diagnostics-drawer" in css
    assert "visibility:hidden!important" in css
    assert "pointer-events:none!important" in css
    assert ".ui4-diagnostics-drawer.open" in css


def test_live_workspace_has_one_authoritative_action_row() -> None:
    css = read("studiox_update15.css")
    script = read("studiox.js")
    assert ".inspector-footer.inspector-command-strip" in css
    assert "display:none!important" in css
    assert 'decisionActions.insertBefore(correctMatch,$("decisionNextButton"))' in script
    assert '.result-decision-actions>#correctMatchButton:not([hidden])' in css


def test_scaled_4k_command_bar_does_not_clip_primary_controls() -> None:
    css = read("studiox_update15.css")
    assert "@media(min-width:1101px) and (max-width:1320px)" in css
    assert 'premium-actions-row>[data-ui4-action="health"]' in css
    assert "overflow:hidden!important" in css


def test_ui4_foundation_tokens_cover_mobile_and_accessibility_contracts() -> None:
    tokens = read("studiox_ui4_tokens.css")
    assert "body.studiox-ui4" in tokens
    for marker in (
        "--ui4-space-1", "--ui4-font-xs", "--ui4-control-default",
        "--ui4-touch-target:44px", "--ui4-radius-md", "--ui4-surface-1",
        "--ui4-border-subtle", "--ui4-shadow-panel", "--ui4-inspector-wide",
        "--ui4-dock-wide", "--ui4-safe-top:env(safe-area-inset-top,0px)",
        "--ui4-viewport-small:100svh", "--ui4-viewport-dynamic:100dvh",
        "--ui4-status-info", "--ui4-focus-ring", "--ui4-transition-default",
        "@media(prefers-reduced-motion:reduce)",
    ):
        assert marker in tokens


def test_update15_component_rules_are_scoped() -> None:
    css = read("studiox_update15.css")
    selector_lines = [
        line.strip() for line in css.splitlines()
        if line.strip().startswith(("body", ":root"))
    ]
    assert selector_lines
    assert all(
        line.startswith(("body.studiox-ui4", "body.studiox-premium"))
        for line in selector_lines
    )


def test_native_shell_width_override_is_declared_once() -> None:
    css = read("studiox_update15.css")
    declaration = "--sx-shell-sidebar-width:148px!important"
    assert css.count(declaration) == 1


def test_information_first_inspector_uses_tiered_responsive_widths() -> None:
    css = read("studiox_update15.css")
    assert '@media(min-width:1101px) and (max-width:1360px)' in css
    assert 'clamp(400px,36vw,460px)' in css
    assert '@media(min-width:1361px)' in css
    assert 'clamp(560px,38vw,760px)' in css
    assert 'grid-template-rows:auto minmax(0,1fr)!important;overflow:hidden!important' in css
    assert 'overflow-y:auto!important' in css


def test_inspector_divider_supports_pointer_and_keyboard_resizing() -> None:
    script = read("studiox.js")
    assert 'handle.setAttribute("role","separator")' in script
    assert 'handle.setAttribute("aria-orientation","vertical")' in script
    assert '["ArrowLeft","ArrowRight","Home","End"]' in script
    assert 'event.shiftKey?40:16' in script
    assert 'commitInspectorWidth' in script


def test_shell_uses_one_consistent_eight_pixel_gap() -> None:
    css = read("studiox_update15.css")
    final_shell = css[css.rindex("/* Rail-aligned shell") :]
    assert "--sx-shell-x:8px" in final_shell
    assert "padding:0 var(--sx-shell-x) var(--sx-shell-x)!important" in final_shell


def test_installer_allowlist_is_frontend_and_tests_only() -> None:
    installer = (ROOT / "updates" / "RareIQ_6.4_Update_15.py").read_text(encoding="utf-8")
    assert "studiox_ui4_tokens.css" in installer
    assert "test_update_15_studiox_responsive_ui.py" in installer
    forbidden = (
        "rareiq/services/", "rareiq/core/", "artwork_index.json",
        "catalog_master/", "captures/", "secrets", "storage",
    )
    targets = installer[installer.index("TARGETS ="):installer.index("PYTHON_TARGETS")]
    assert not any(value in targets for value in forbidden)


def test_camera_scan_stage_has_authoritative_density_caps() -> None:
    css = read("studiox_update15.css")
    cap = css[css.rindex("Final scan-stage sizing contract") :]
    assert '--sx-scan-stage-cap:min(70dvh,780px)' in cap
    assert '[data-workspace-density="compact"]{--sx-scan-stage-cap:min(58dvh,640px)' in cap
    assert '[data-workspace-density="focus"]{--sx-scan-stage-cap:min(82dvh,920px)' in cap
    assert '--sx-scan-stage-floor:min(360px,calc(100dvh - 104px))' in cap
    assert 'max-height:var(--sx-scan-stage-cap)!important' in cap
    assert 'height:100%!important;min-height:0!important;max-height:none!important' not in cap
    aspect_cap = css[css.rindex("Aspect-aware scan canvas") :]
    assert "container-type:inline-size" in aspect_cap
    assert "calc(56.25cqw + 106px)" in aspect_cap
    assert "object-fit:contain!important" in aspect_cap


def test_inspector_diagnostics_keep_readable_type_and_non_overlapping_rows() -> None:
    css = read("studiox_update15.css")
    contract = css[css.rindex("Inspector legibility contract") :]
    assert "--sx-inspector-copy:clamp(11px" in contract
    assert "--sx-inspector-label:clamp(9px" in contract
    assert "grid-template-rows:auto auto auto!important" in contract
    assert "grid-row:3!important" in contract
    assert "grid-template-columns:repeat(4,minmax(92px,1fr))!important" in contract
    assert "white-space:normal!important" in contract
    assert "min-width:64px!important" in contract
    assert "height:32px!important" in contract


def test_draggable_tool_content_inherits_inspector_legibility_contract() -> None:
    css = read("studiox_update15.css")
    contract = css[css.rindex("Inspector legibility contract") :]
    assert ".studiox-widget-content" in contract
    assert "font-size:var(--sx-inspector-copy)!important" in contract
    assert ".studiox-identity-evidence-heading strong" in contract
    assert ".studiox-identity-evidence-heading small" in contract
    assert "overflow-wrap:anywhere!important" in contract

