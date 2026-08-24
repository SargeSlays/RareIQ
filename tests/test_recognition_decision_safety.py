import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from starlette.responses import JSONResponse

from rareiq.web import server


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "rareiq" / "web" / "static" / "studiox.js").read_text(
    encoding="utf-8"
)


class _Status:
    def status(self):
        return {}


class _RecognitionState:
    def refresh(self, **_kwargs):
        return {"state_id": "current-card"}


class _DecisionOrchestrator:
    def __init__(self):
        self.recognition_state = _RecognitionState()
        self.vision = _Status()
        self.recognition = _Status()
        self.catalog = _Status()
        self.confirmed = 0
        self.rejected = 0

    async def confirm_recognition(self, **_kwargs):
        self.confirmed += 1
        return {"ok": True}

    async def reject_recognition(self):
        self.rejected += 1
        return {"ok": True}


def _response_payload(response: JSONResponse) -> dict:
    return json.loads(response.body.decode("utf-8"))


def test_stale_manual_decisions_cannot_mutate_a_newer_card(monkeypatch):
    fake = _DecisionOrchestrator()
    monkeypatch.setattr(server, "orchestrator", fake)

    approved = asyncio.run(server.confirm_recognition("previous-card"))
    rejected = asyncio.run(server.reject_recognition("previous-card"))

    assert approved.status_code == 409
    assert rejected.status_code == 409
    assert _response_payload(approved)["reason"] == "stale_recognition_state"
    assert _response_payload(rejected)["current_state_id"] == "current-card"
    assert fake.confirmed == 0
    assert fake.rejected == 0


def test_current_manual_decisions_remain_available(monkeypatch):
    fake = _DecisionOrchestrator()
    monkeypatch.setattr(server, "orchestrator", fake)

    assert asyncio.run(server.confirm_recognition("current-card"))["ok"] is True
    assert asyncio.run(server.reject_recognition("current-card"))["ok"] is True
    assert fake.confirmed == 1
    assert fake.rejected == 1


def test_next_clear_is_one_shot_and_restores_controls_after_failure():
    start = SCRIPT.index("async function requestNextRecognition")
    section = SCRIPT[start : start + 1800]

    assert "if(recognitionMutationInFlight()) return null" in section
    assert "recognitionClearInFlight=true" in section
    assert "recognitionClearInFlight=false" in section
    assert 'button.textContent="Clearing…"' in section
    assert 'notify("Next Card Failed"' in section
    assert 'delete document.body.dataset.cardHandoff' in section
    assert "syncRecognitionMutationControls()" in section


def test_all_card_mutations_share_one_busy_gate():
    assert "function recognitionMutationInFlight()" in SCRIPT
    assert '["nextClearButton","decisionNextButton","mobileOperatorNext","correctMatchButton"]' in SCRIPT
    assert "const actionable=context.verified===true&&!recognitionMutationInFlight()" in SCRIPT
    assert '$("nextClearButton").disabled=recognitionMutationInFlight()' in SCRIPT
