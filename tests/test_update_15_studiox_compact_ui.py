from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "rareiq" / "web" / "static"


def read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_compact_pipeline_has_exact_order_and_accessible_waiting_state() -> None:
    html = read("control.html")
    rail_start = html.index('class="pipeline pipeline-rail ui4-pipeline-region"')
    rail = html[rail_start:html.index("</div>\n          </div>", rail_start)]
    labels = re.findall(r'<div class="process pipeline-step"[^>]*>\s*<span[^>]*>.*?</span><b>([^<]+)</b>', rail)
    assert labels == ["Detect", "Stabilize", "Capture", "Recognize", "Match"]
    assert rail.count('role="listitem"') == 5
    assert rail.count('data-state="waiting"') == 5
    assert len(re.findall(r'aria-label="(?:Detect|Stabilize|Capture|Recognize|Match): Waiting"', rail)) == 5
    assert 'role="list"' in rail


def test_pipeline_supports_exact_canonical_states_and_aliases() -> None:
    script = read("studiox.js")
    assert 'const PIPELINE_STATES=["waiting","active","complete","warning","failed","skipped"]' in script
    expected_aliases = {
        "detect": ["detect", "detection", "visible", "card_detected"],
        "stabilize": ["stabilize", "acquiring", "stable", "lock", "card_locked"],
        "capture": ["capture", "prepare", "crop", "card_captured"],
        "recognize": ["recognize", "read", "ocr", "searching", "recognition"],
        "match": ["match", "artwork", "verify", "verified", "candidate"],
    }
    for key, aliases in expected_aliases.items():
        rendered = ",".join(f'"{alias}"' for alias in aliases)
        assert f'key:"{key}",label:' in script
        assert f"aliases:[{rendered}]" in script


def test_pipeline_normalization_is_safe_and_failure_precedes_completion() -> None:
    script = read("studiox.js")
    start = script.index("function normalizePipelineState")
    end = script.index("function renderPipeline", start)
    normalize = script[start:end]
    assert 'return "failed"' in normalize
    assert 'return "warning"' in normalize
    assert 'return "skipped"' in normalize
    assert 'return "complete"' in normalize
    assert 'return "active"' in normalize
    assert normalize.rstrip().endswith('return "waiting";\n}')
    assert script.index("stage.failed===true", start, end) < script.index("stage.done===true", start, end)
    assert "const precedence={failed:6,warning:5,active:4,complete:3,skipped:2,waiting:1}" in script


def test_only_one_active_step_receives_aria_current() -> None:
    script = read("studiox.js")
    assert "let activeClaimed=false" in script
    assert 'if(activeClaimed) state="waiting"' in script
    assert 'el.setAttribute("aria-current","step")' in script
    assert 'el.removeAttribute("aria-current")' in script


def test_empty_and_server_session_resets_keep_existing_guards() -> None:
    script = read("studiox.js")
    reset_start = script.index("function resetRecognitionPresentation")
    reset_end = script.index("async function loadRecognition", reset_start)
    reset = script[reset_start:reset_end]
    assert "renderPipeline([],false)" in reset
    assert '$(`cardArt`)' not in reset
    assert '$(("cardArt"))' not in reset
    assert '$("cardArt").innerHTML=""' in reset
    assert 'resetRecognitionPresentation("backend_empty")' in script
    assert 'hadPreviousSession ? "server_session_changed"' in script
    assert "newestRecognitionGeneration=-1" in script
    assert "newestRecognitionRevision=-1" in script


def test_warning_failed_and_skipped_have_non_color_indicators() -> None:
    script = read("studiox.js")
    assert 'warning:"Warning",failed:"Failed",skipped:"Skipped"' in script
    assert 'warning:"!",failed:"×",skipped:"–"' in script
    assert 'icon.textContent=PIPELINE_STATE_ICONS[state]' in script
    assert 'statusNode.textContent=status' in script


def test_update15_stylesheet_is_last_and_cache_busted() -> None:
    html = read("control.html")
    links = re.findall(r'<link rel="stylesheet" href="([^"]+)"', html)
    active_version = re.search(r'data-studiox-build="([^"]+)"', html).group(1)
    assert links[-3:] == [
        f"/static/studiox_ui4_tokens.css?v={active_version}",
        f"/static/studiox_update15.css?v={active_version}",
        f"/static/pack_run_coach.css?v={active_version}",
    ]
    assert f'/static/studiox.js?v={active_version}' in html


def test_compact_controls_and_primary_breakpoints_are_contractual() -> None:
    css = read("studiox_update15.css")
    assert "--update15-control-height:var(--ui4-control-default)" in css
    assert "min-height:var(--ui4-control-compact)" in css
    assert "max-height:var(--ui4-control-large)" in css
    assert "--update15-dock-height:var(--ui4-dock-wide)" in css
    assert "--update15-inspector-width:var(--ui4-inspector-wide)" in css
    assert "@media(max-width:1366px), (max-height:768px)" in css
    assert "--update15-dock-height:var(--ui4-dock-compact)" in css
    assert "--update15-inspector-width:var(--ui4-inspector-compact)" in css
    assert "grid-template-columns:repeat(5,minmax(0,1fr))" in css
    assert "height:100dvh" in css
    assert "overflow:hidden" in css
    assert "body ." not in css
    assert "body.studiox-ui4" in css


def test_existing_control_ids_and_handlers_are_preserved() -> None:
    html = read("control.html")
    ids = {
        "cameraSelect", "restartFeedBtn", "autoCaptureToggle", "cameraFeed",
        "cameraFitToggle", "cameraZoomToggle", "scanZone", "inspectorEmpty",
        "inspectorMain", "cardArt", "approveButton", "rejectButton",
        "detailsButton", "dockToggle", "recognitionStatePanel",
    }
    for element_id in ids:
        assert f'id="{element_id}"' in html
    handlers = {
        "selectCamera()",
        "startSelectedCamera()", "stopCamera()", "captureCamera()",
        "toggleAutoCapture()", "openCameraPopout()", "cycleCameraFit()",
        "toggleCardZoom()", "toggleDock()",
    }
    for handler in handlers:
        assert handler in html
    for handler in ("loadCameraList", "reconnectCamera", "restartFeed"):
        assert handler in read("studiox.js")


def test_all_intelligence_widgets_support_persistent_drag_reordering() -> None:
    script = read("studiox.js")
    css = read("studiox_update15.css")
    assert 'data-widget-drag-handle="${id}"' in script
    # The primary Identify tool is user-orderable too; no tool receives a
    # hard-coded exemption from the saved layout.
    assert 'sourceId==="identify"' not in script
    assert 'targetId==="identify"' not in script
    assert 'spotify:"Spotify DJ"' in script
    assert 'function reorderStudioXWidgetByDrop' in script
    assert 'widgetWorkspace.addEventListener("dragstart"' in script
    assert 'widgetWorkspace.addEventListener("dragover"' in script
    assert 'widgetWorkspace.addEventListener("drop"' in script
    assert 'applyStudioXWidgetLayout({persist:true})' in script
    assert ".studiox-widget-drag-handle" in css
    assert ".studiox-widget.is-drop-before::before" in css
    assert ".studiox-widget.is-drop-after::after" in css


def test_camera_and_recognition_contracts_remain_present() -> None:
    script = read("studiox.js")
    for marker in (
        "vision.actual_resolution", "vision.scan_zone", "manager.frame_fresh===true",
        "result?.recognition_state", "newestRecognitionGeneration",
        "newestRecognitionRevision", "currentServerSessionId",
    ):
        assert marker in script
