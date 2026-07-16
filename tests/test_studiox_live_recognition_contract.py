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

    assert "/static/studiox.js?v=6.4.12" in html
    assert "/static/studiox.css?v=6.4.12" in html
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

