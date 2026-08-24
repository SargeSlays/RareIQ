from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "rareiq" / "web" / "static"


def read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8-sig")


def function_body(script: str, name: str, next_name: str) -> str:
    start = script.index(f"function {name}")
    end = script.index(f"function {next_name}", start)
    return script[start:end]


def test_checkpoint_camera_viewport_and_scan_zone_contracts_are_restored() -> None:
    html = read("control.html")
    script = read("studiox.js")
    css = read("studiox_update15.css")
    legacy = read("studiox.css")
    assert html.count('id="cameraFeed"') == 1
    assert len(re.findall(r'<img[^>]+id="cameraFeed"', html)) == 1
    assert script.count("/api/camera/stream") == 3
    assert 'const feed=$("cameraFeed")' in script
    assert 'feed.src=`/api/camera/stream?viewer=main&ts=${Date.now()}&generation=${viewerBridgeGeneration}`' in script
    assert 'feed.src=`/api/camera/stream?ts=${Date.now()}&retry=${cameraStreamFailures}`' in script
    assert '"/api/camera/stream?viewer=secondary-card-focus"' in script
    assert ".camera-stage-inner{inset:0;" in css
    assert "inset:0 0 52px" not in css
    assert ".camera-feed{\n  width:100%;height:100%;object-fit:contain;display:block;\n}" in legacy
    assert ".scan-zone{left:10%;top:8%;width:80%;height:84%;bottom:auto;" in css
    assert "function alignScanZone(vision={})" in script
    assert "const zoneValues=vision.scan_zone||{" in script
    assert "left:0.10,top:0.08,right:0.90,bottom:0.92" in script


def test_primary_inspector_views_are_accessible_and_current_is_default() -> None:
    html = read("control.html")
    script = read("studiox.js")
    assert 'role="tablist" aria-label="Inspector views"' in html
    assert 'role="tab" data-inspector-view="current" aria-selected="true"' in html
    assert 'role="tab" data-inspector-view="recent" aria-selected="false"' in html
    assert 'setUI4InspectorView("current",false)' in script
    assert 'button.setAttribute("aria-selected",selected?"true":"false")' in script
    assert "button.tabIndex=selected?0:-1" in script


def test_recent_scans_use_existing_history_once_and_render_newest_first() -> None:
    script = read("studiox.js")
    loader = function_body(script, "loadUI4RecentScans", "setUI4InspectorView")
    renderer = function_body(script, "renderUI4RecentScans", "loadUI4RecentScans")
    assert script.count('/api/recent-pulls?limit=20') == 1
    assert "Number(right.timestamp||0)-Number(left.timestamp||0)" in renderer
    assert ".slice(0,20)" in renderer
    assert 'title.textContent="No recent scans"' in renderer
    assert "renderUI4RecentScans(Array.isArray(payload.cards)?payload.cards:[])" in loader
    assert script.count("setInterval(loadRecognition,600)") == 1
    assert "setInterval(loadUI4RecentScans" not in script


def test_history_selection_is_read_only_and_does_not_touch_ordering_guards() -> None:
    script = read("studiox.js")
    history = script[
        script.index("function recentScanConfidence"):
        script.index("function initializeStudioXUI4")
    ]
    for forbidden in (
        "captureCamera(", "loadRecognition(", "newestRecognitionGeneration=",
        "newestRecognitionRevision=", "/api/camera/capture",
    ):
        assert forbidden not in history
    assert 'live.textContent="Return to Live Card"' in history
    assert 'setUI4InspectorView("current",false)' in history
    assert 'row.addEventListener("click",()=>renderUI4RecentScanDetail(card))' in history


def test_empty_clearing_does_not_force_history_closed_but_session_reset_does() -> None:
    script = read("studiox.js")
    reset = function_body(script, "resetUI4PresentationSurfaces", "recentScanConfidence")
    assert 'setUI4InspectorView("current"' not in reset
    session = script[script.index("if(serverSessionId &&"):script.index("const generation=", script.index("if(serverSessionId &&"))]
    assert 'setUI4InspectorView("current",false)' in session
    assert 'resetRecognitionPresentation("backend_empty")' in script
    assert '$("cardArt").innerHTML=""' in script
