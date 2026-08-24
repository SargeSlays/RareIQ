from pathlib import Path
import asyncio
from types import SimpleNamespace

from rareiq.web import server


ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "rareiq" / "web" / "server.py").read_text(encoding="utf-8")
SCRIPT = (ROOT / "rareiq" / "web" / "static" / "studiox.js").read_text(encoding="utf-8")


def test_provenance_api_routes_are_minimal_and_structured():
    for route in (
        '@app.get("/api/provenance/settings")',
        '@app.put("/api/provenance/settings")',
        '@app.post("/api/provenance/capture")',
        '@app.get("/api/provenance/events")',
        '@app.get("/api/provenance/events/{event_id}")',
        '@app.post("/api/provenance/events/{event_id}/correct")',
        '@app.get("/api/provenance/events/{event_id}/assets/{asset_id}")',
    ):
        assert route in SERVER


def test_next_clear_advances_backend_before_resetting_the_browser():
    assert '@app.post("/api/recognition/clear")' in SERVER
    assert "vision.prepare_next_card" in SERVER
    assert '"type": "card_removed"' in SERVER
    assert 'orchestrator._set_continuous_state(\n        "CHANGING"' in SERVER
    start = SCRIPT.index("async function requestNextRecognition")
    section = SCRIPT[start:start + 900]
    assert 'fetch("/api/recognition/clear",{method:"POST"})' in section
    assert section.index("await fetch") < section.index('resetRecognitionPresentation("operator_clear")')


def test_next_clear_advances_generation_once_and_arms_changing(monkeypatch):
    class FakeState:
        def __init__(self):
            self.generation = 9

        def snapshot(self):
            return {"generation": self.generation, "phase": "CHANGING"}

    state = FakeState()
    transitions = []
    fake = SimpleNamespace(
        camera_manager=SimpleNamespace(
            vision=SimpleNamespace(
                prepare_next_card=lambda: {
                    "frame_id": 44,
                    "auto_capture_armed": True,
                }
            )
        ),
        recognition_state=state,
    )

    def emit(event):
        assert event["type"] == "card_removed"
        state.generation += 1

    fake._emit_from_thread = emit
    fake._set_continuous_state = lambda value, **kwargs: transitions.append(value)
    monkeypatch.setattr(server, "orchestrator", fake)
    result = asyncio.run(server.clear_recognition())
    assert result["recognition_state"]["generation"] == 10
    assert transitions == ["CHANGING"]
    assert result["vision"]["auto_capture_armed"] is True


def test_recognition_event_integration_is_not_a_polling_capture_loop():
    assert 'event.get("type") or "") != "recognition_update"' in SERVER
    assert "asyncio.to_thread(provenance_capture.evaluate_recognition" in SERVER
    recognition_poll = SCRIPT[SCRIPT.index('`/api/recognition-state?t='):]
    assert "/api/provenance/capture" not in recognition_poll[:2000]


def test_frontend_loads_settings_and_requires_backend_confirmation():
    assert 'requestAutoScreenshotBackend("/api/provenance/settings")' in SCRIPT
    assert 'requestAutoScreenshotBackend("/api/provenance/capture",{method:"POST"})' in SCRIPT
    assert "result.eventId" in SCRIPT
    assert "AUTO_SCREENSHOT_BACKEND_AVAILABLE=payload.available===true" in SCRIPT
    assert "Screenshot capture engine not connected" in SCRIPT


def test_manual_failure_is_logged_and_returns_no_success_contract():
    assert "provenance_manual_capture_failed" in SERVER
    assert "return JSONResponse(status_code=409, content=result)" in SERVER
