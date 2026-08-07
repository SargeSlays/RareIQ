from pathlib import Path


def test_studiox_uses_recognition_state_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (
        root
        / "rareiq"
        / "web"
        / "static"
        / "studiox.js"
    ).read_text(
        encoding="utf-8"
    )

    assert "result?.recognition_state" in script
    assert "/api/recognition-state?t=${Date.now()}" in script
    assert "snapshot.primary_candidate" in script
    assert "snapshot?.pipeline_stages" in script
    assert "window.__rareiqRecognitionPoll" in script
    assert "verifiedVisualCandidate" in script
    assert "realIdentityCandidate" in script
    assert "candidate.verification_strong === true" in script
    assert "databaseCandidate ||" not in script
    assert "snapshot?.overall_confidence ??\n      snapshot?.confidence" not in script
    assert "currentServerSessionId" in script
    assert "result?.server_session_id" in script
    assert 'resetRecognitionPresentation("backend_empty")' in script
    assert "newestRecognitionGeneration=-1" in script
    assert "newestRecognitionRevision=-1" in script
    assert 'hadPreviousSession ? "server_session_changed"' in script
    assert 'if(serverSessionId && serverSessionId!==currentServerSessionId)' in script


def test_server_exposes_process_stable_session_id_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    server = (root / "rareiq" / "web" / "server.py").read_text(
        encoding="utf-8"
    )
    assert "SERVER_SESSION_ID = uuid.uuid4().hex" in server
    assert server.count('"server_session_id": SERVER_SESSION_ID') >= 3


def test_empty_and_server_change_remove_previous_artwork_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "rareiq" / "web" / "static" / "studiox.js").read_text(
        encoding="utf-8"
    )
    reset_start = script.index("function resetRecognitionPresentation")
    reset_end = script.index("async function loadRecognition", reset_start)
    reset = script[reset_start:reset_end]
    assert '$("cardArt").innerHTML=""' in reset
    assert '$("cardName").textContent="Ready to Scan"' in reset
    assert '$("confidence").textContent="0%"' in reset
    assert '$("cardStatus").textContent="READY"' in reset
    assert 'renderPipeline([],false)' in reset


def test_control_html_busts_studiox_cache() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (
        root
        / "rareiq"
        / "web"
        / "static"
        / "control.html"
    ).read_text(
        encoding="utf-8"
    )

    assert "/static/studiox.js?v=6.4.15-shellbay29" in html
    assert "/static/studiox.css?v=6.4.12" in html
    assert "/static/studiox_ui4_tokens.css?v=6.4.15-shellbay29" in html
    assert "/static/studiox_update15.css?v=6.4.15-shellbay29" in html
    assert html.index("studiox_ui4_tokens.css") < html.index("studiox_update15.css")
    assert html.index("studiox_update15.css") < html.index("studiox.js?v=6.4.15")
    assert 'http-equiv="Cache-Control"' in html


def test_studiox_renders_camera_resolution_and_scan_zone() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (
        root / "rareiq" / "web" / "static" / "studiox.js"
    ).read_text(encoding="utf-8")
    stylesheet = (
        root / "rareiq" / "web" / "static" / "studiox.css"
    ).read_text(encoding="utf-8")

    assert "vision.actual_resolution" in script
    assert "vision.requested_resolution" in script
    assert "vision.resolution_fallback" in script
    assert "vision.scan_zone" in script
    assert "function alignScanZone" in script
    assert 'fit==="cover"' in script
    assert 'fit==="contain"' not in script
    assert ".riq-pill.fallback" in stylesheet


def test_studiox_requires_authoritative_fresh_camera_health() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "rareiq" / "web" / "static" / "studiox.js").read_text(
        encoding="utf-8"
    )
    assert 'manager.state==="running"' in script
    assert 'manager.worker_alive===true' in script
    assert 'manager.frame_fresh===true' in script
    assert 'vision.running===true' in script
    assert '"CAMERA STALLED"' in script
    assert 'result?.already_running' in script
    assert 'status?.running ||' not in script

