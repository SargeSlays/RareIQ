import asyncio
import json
from pathlib import Path

from rareiq.services.sarge_advisor_service import SargeAdvisorService


ROOT = Path(__file__).resolve().parents[1]
CONTROL = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8-sig")
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")
COMMAND_DECK = (ROOT / "rareiq/web/static/studiox_command_deck.css").read_text(encoding="utf-8")


def conflicting_context():
    return {
        "recognition": {
            "state_id": "card-state-1",
            "generation": 4,
            "phase": "ARTWORK MATCH",
            "verification_state": "SEARCHING",
            "overall_confidence": 0.80,
            "has_reference_evidence": False,
            "card_present": True,
            "result_current": False,
            "ocr_collector_number": "029/084",
            "language": "Chinese",
            "candidate_count": 10,
            "primary_candidate": None,
            "candidates": [
                {
                    "id": "me05-029",
                    "english_name": "Slowpoke",
                    "collector_number": "029/120",
                    "language": "Italian",
                    "image_path": "F:/private/card.png",
                    "verification_strong": True,
                }
            ],
            "secret": "must-not-leak",
        },
        "card": {"card_name": "Slowpoke", "raw_value": 0},
        "camera": {"state": "running", "frame_fresh": True, "visible": True, "stable": True},
        "session": {"active": True, "card_count": 2},
        "broadcast": {"active": False},
        "filesystem_path": "C:/private/database.json",
    }


def test_local_advisor_explains_identity_conflicts_without_mutating_state():
    service = SargeAdvisorService()
    result = asyncio.run(
        service.ask(
            "Why is this card not verified?",
            conflicting_context(),
            scope="current-card",
        )
    )

    assert result["ok"] is True
    assert result["source"] == "local_rareiq"
    assert result["advisory_only"] is True
    assert result["mutations_performed"] is False
    assert "Slowpoke" in result["answer"]
    assert "029/084" in result["answer"]
    assert "029/120" in result["answer"]
    assert "Keep approval blocked" in result["suggestions"]


def test_advisor_context_excludes_paths_images_and_secrets():
    safe = SargeAdvisorService.sanitize_context(conflicting_context())
    encoded = json.dumps(safe)

    assert "must-not-leak" not in encoded
    assert "private/card.png" not in encoded
    assert "private/database.json" not in encoded
    assert "image_path" not in encoded
    assert safe["recognition"]["candidates"][0]["id"] == "me05-029"


def test_sarge_adapter_uses_the_versioned_read_only_contract():
    class ConnectedAdvisor(SargeAdvisorService):
        def __init__(self):
            super().__init__("http://127.0.0.1:9909/v1/rareiq/suggestions", token="secret")
            self.payload = None

        async def _ask_sarge(self, payload):
            self.payload = payload
            return {
                "answer": "Use the current evidence.",
                "suggestions": ["Review identifiers"],
                "evidence": ["Collector number available"],
            }

    service = ConnectedAdvisor()
    result = asyncio.run(service.ask("What next?", conflicting_context()))

    assert result["source"] == "sarge_ai"
    assert service.payload["version"] == 1
    assert service.payload["safety"] == {"mode": "advisory", "mutationsAllowed": False}
    assert "secret" not in json.dumps(service.payload)
    assert service.status()["endpoint_host"] == "127.0.0.1:9909"


def test_advisor_api_and_ui_are_explicit_and_one_shot():
    assert '@app.get("/api/ai/advisor/status")' in SERVER
    assert '@app.post("/api/ai/advisor/ask")' in SERVER
    assert "class AdvisorQuestionRequest" in SERVER
    assert 'id="aiLabTabAdvisor"' in CONTROL
    assert 'id="sargeAdvisorForm"' in CONTROL
    assert 'id="sargeAdvisorResponse" hidden' in CONTROL
    advisor = SCRIPT[SCRIPT.index("let sargeAdvisorInFlight"):SCRIPT.index("async function loadAiLab")]
    assert "if(sargeAdvisorInFlight)return null" in advisor
    assert 'api("/api/ai/advisor/ask",{method:"POST"' in advisor
    assert "setInterval" not in advisor
    assert "renderSargeAdvisorAnswer" in advisor
    assert ".innerHTML" not in advisor


def test_live_card_workbench_exposes_the_same_one_shot_advisor():
    assert CONTROL.count('data-studiox-widget="sarge-advisor"') == 1
    assert 'data-widget-visibility="sarge-advisor"' in CONTROL
    assert 'id="liveSargeAdvisorForm"' in CONTROL
    assert 'id="liveSargeAdvisorQuestion"' in CONTROL
    assert 'id="liveSargeAdvisorResponse" hidden' in CONTROL
    assert '"sarge-advisor":"Ask Sarge"' in SCRIPT
    assert 'card:["identify","sarge-advisor"' in SCRIPT
    assert 'recognition:["identify","sarge-advisor"' in SCRIPT
    live = SCRIPT[SCRIPT.index("let liveSargeAdvisorInFlight"):SCRIPT.index("async function loadSargeAdvisorStatus")]
    assert "if(liveSargeAdvisorInFlight)return null" in live
    assert "requestSargeAdvisor(question" in live
    assert "setInterval" not in live
    assert ".innerHTML" not in live


def test_live_advisor_prompts_fill_the_question_without_automatic_submission():
    initializer = SCRIPT[SCRIPT.index("function initializeAiLab"):SCRIPT.index("const LIBRARY_VIEW_KEY")]
    prompt_handler = initializer[initializer.index('[data-live-sarge-question]'):]
    assert "dataset.liveSargeQuestion" in prompt_handler
    assert ".focus()" in prompt_handler
    assert "requestSubmit" not in prompt_handler


def test_missing_sarge_configuration_is_truthful_and_still_useful():
    status = SargeAdvisorService().status()
    assert status["configured"] is False
    assert status["mode"] == "local_rareiq"
    assert status["provider"] == "RareIQ Local Advisor"
    assert status["mutations_allowed"] is False
    assert status["images_shared"] is False


def test_ai_lab_advisor_uses_the_shared_command_deck_visual_system():
    assert '.workspace[data-workspace="ai"] .sarge-advisor-card {' in COMMAND_DECK
    assert 'border-left: 3px solid var(--sx-accent-strong) !important;' in COMMAND_DECK
    assert '.workspace[data-workspace="ai"] .sarge-advisor-form textarea' in COMMAND_DECK
    assert 'background: var(--sx-surface-muted) !important;' in COMMAND_DECK
    assert '.workspace[data-workspace="ai"] .sarge-advisor-columns {' in COMMAND_DECK


def test_provisional_market_value_is_never_described_as_verified():
    context = conflicting_context()
    context["card"]["raw_value"] = 999.99
    context["card"]["verification_state"] = "PROVISIONAL"
    service = SargeAdvisorService()
    result = asyncio.run(service.ask("Is this ready to sell?", context))

    assert "Verified card value" not in result["evidence"]
    assert "No truthful market value is available" in result["evidence"]
