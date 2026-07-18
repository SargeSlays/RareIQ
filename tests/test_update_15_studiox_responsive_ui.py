from __future__ import annotations

import hashlib
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "rareiq" / "web" / "static"


def read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8-sig")


def test_all_existing_ids_remain_unique() -> None:
    html = read("control.html")
    ids = re.findall(r'\bid="([^"]+)"', html)
    unique = sorted(set(ids))
    digest = hashlib.sha256("\n".join(unique).encode()).hexdigest()
    assert len(ids) == 124
    assert len(unique) == 124
    assert digest == "7551920178ed2cbc4b568ead86729f4fc66bf49b1d35521f117a35ffaa631c5d"


def test_one_camera_feed_and_no_video_clone() -> None:
    html = read("control.html")
    assert html.count('id="cameraFeed"') == 1
    assert len(re.findall(r'<img[^>]+id="cameraFeed"', html)) == 1
    assert "<video" not in html.lower()
    assert html.count("/api/camera/stream") == 0


def test_ui4_scope_and_semantic_regions_exist_without_new_functional_ids() -> None:
    html = read("control.html")
    assert '<body class="studiox-ui4" data-ui4-region="application-shell">' in html
    for region in (
        "top-app-bar", "controls", "camera", "current-card", "pipeline",
        "diagnostics", "product-navigation", "mobile-actions",
    ):
        assert f'data-ui4-region="{region}"' in html
    assert 'class="ui4-mobile-action-region"' in html
    assert 'class="studiox-ui4"' in html
    assert 'class="app-actions ui4-app-health"' in html
    assert 'class="command-group ui4-program-actions"' in html


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
    assert html.count('class="nav-button') == 7
    assert html.count('data-panel=') == 7
    assert 'camera.appendChild(pipeline)' in script
    assert 'dock.classList.add("ui4-diagnostics-drawer")' in script
    assert 'camera.appendChild(dock)' in script
    assert '["details","Details",null]' in script
    for key in ("market", "copilot", "signals", "session"):
        assert f'["{key}"' in script


def test_presentation_state_is_local_and_api_free() -> None:
    script = read("studiox.js")
    start = script.index("function setUI4DiagnosticsOpen")
    end = script.index('document.addEventListener("DOMContentLoaded"', start)
    presentation = script[start:end]
    assert "fetch(" not in presentation
    assert presentation.count("api(") == 1
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
        "selectCamera()", "loadCameraList()", "reconnectCamera()", "restartFeed()",
        "startSelectedCamera()", "stopCamera()", "captureCamera()",
        "toggleAutoCapture()", "openCameraPopout()", "cycleCameraFit()",
        "toggleCardZoom()", "operatorApprove()", "operatorReject()",
        "operatorDetails()", "toggleDock()", "openProgram()",
    )
    for handler in handlers:
        assert handler in html
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
    assert script.count("/api/camera/stream") == 2
    assert script.count("setInterval(loadRecognition,600)") == 1


def test_ui4_stylesheets_are_cache_busted_and_last_in_cascade() -> None:
    html = read("control.html")
    styles = re.findall(r'<link rel="stylesheet" href="([^"]+)"', html)
    assert styles[-2:] == [
        "/static/studiox_ui4_tokens.css?v=6.4.15-ui4structural",
        "/static/studiox_update15.css?v=6.4.15-carddata1",
    ]
    assert len(styles) == 19


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
    assert all(line.startswith("body.studiox-ui4") for line in selector_lines)


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

