from __future__ import annotations

import hashlib
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "rareiq" / "web" / "static"


def read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8-sig")


def test_all_91_existing_ids_remain_unique() -> None:
    html = read("control.html")
    ids = re.findall(r'\bid="([^"]+)"', html)
    unique = sorted(set(ids))
    digest = hashlib.sha256("\n".join(unique).encode()).hexdigest()
    assert len(ids) == 91
    assert len(unique) == 91
    assert digest == "3ffee1c37d61d08ed569811c7f9caab7ba813f08872fd29735e24d554c7f9331"


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


def test_phase2_desktop_hierarchy_prioritizes_camera_and_compact_inspector() -> None:
    css = read("studiox_update15.css")
    tokens = read("studiox_ui4_tokens.css")
    assert "grid-template-columns:minmax(210px,auto) minmax(420px,1fr) auto auto" in css
    assert "flex-wrap:nowrap" in css
    assert "grid-template-columns:minmax(0,1fr) var(--update15-inspector-width)" in css
    assert "--ui4-inspector-wide:380px" in tokens
    assert "--ui4-inspector-ultrawide:440px" in tokens
    assert "@media(min-width:2200px) and (min-height:1200px)" in css
    assert "overflow-x" not in css


def test_phase2_inspector_and_diagnostics_keep_operator_hierarchy() -> None:
    html = read("control.html")
    css = read("studiox_update15.css")
    for marker in (
        ".inspector-head{order:0}", ".recognition-state{order:1}",
        ".inspector-footer{order:3}", ".copilot-card{order:4}",
        ".session-strip{order:5}",
    ):
        assert marker in css
    for tab in ("Thinking", "Candidates", "OCR", "Session", "Telemetry", "Recent Pulls", "Activity"):
        assert f'>{tab}</button>' in html
    assert html.count('class="nav-button') == 7


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
        "/static/studiox_ui4_tokens.css?v=6.4.15-ui4p2",
        "/static/studiox_update15.css?v=6.4.15-ui4p2",
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
