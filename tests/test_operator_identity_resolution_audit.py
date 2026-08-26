import asyncio
import json
from pathlib import Path

from rareiq.services.learning_queue_service import LearningQueueService
from rareiq.services.session_service import SessionService
from rareiq.web import server


SNAPSHOT = {
    "state_id": "state-review-1",
    "verification_state": "REVIEW_NEEDED",
    "artwork_fingerprint": "0123456789abcdef",
    "identity_evidence": {
        "observed": {"collector_number": "029/084", "language": "Chinese"},
        "catalog": {"id": "wrong", "collector_number": "092/210", "language": "Japanese"},
    },
    "identity_conflicts": [
        {"field": "collector_number", "observed": "029/084", "catalog": "092/210"},
        {"field": "language", "observed": "Chinese", "catalog": "Japanese"},
    ],
    "candidates": [
        {
            "id": "correct-card",
            "card_name": "Card 029/084",
            "collector_number": "029/084",
            "language": "Simplified Chinese",
            "confidence": 0.9,
        }
    ],
}


class _RecognitionState:
    def __init__(self, snapshot=None):
        self._snapshot = snapshot or SNAPSHOT

    def snapshot(self):
        return self._snapshot


class _Orchestrator:
    def __init__(self, root: Path, snapshot=None):
        self.recognition_state = _RecognitionState(snapshot)
        self.learning_queue = LearningQueueService(root)
        self.confirmed = None

    async def confirm_recognition(self, **kwargs):
        self.confirmed = kwargs["card_override"]
        return {"ok": True, "session": {"card_count": 1}}


def test_ranked_candidate_resolution_preserves_the_original_conflict(monkeypatch, tmp_path):
    fake = _Orchestrator(tmp_path / "learning")
    monkeypatch.setattr(server, "orchestrator", fake)
    request = server.RecognitionCandidateSelectionRequest(
        state_id="state-review-1", candidate_index=0
    )

    result = asyncio.run(server.confirm_recognition_candidate(request))

    resolution = result["operator_resolution"]
    assert resolution["selection_source"] == "ranked_candidate"
    assert resolution["observed_identity"] == {
        "collector_number": "029/084", "language": "Chinese"
    }
    assert resolution["previous_catalog_identity"]["id"] == "wrong"
    assert resolution["selected_identity"]["id"] == "correct-card"
    assert len(resolution["prior_conflicts"]) == 2
    assert fake.confirmed["operator_resolution"] == resolution
    assert result["learning"]["correction"]["resolution"] == resolution


def test_stale_ranked_candidate_cannot_confirm_or_create_learning(monkeypatch, tmp_path):
    fake = _Orchestrator(tmp_path / "learning")
    monkeypatch.setattr(server, "orchestrator", fake)
    request = server.RecognitionCandidateSelectionRequest(
        state_id="previous-card", candidate_index=0
    )

    try:
        asyncio.run(server.confirm_recognition_candidate(request))
    except server.HTTPException as exc:
        assert exc.status_code == 409
        assert "Recognition changed" in str(exc.detail)
    else:
        raise AssertionError("stale candidate selection unexpectedly succeeded")

    assert fake.confirmed is None
    assert fake.learning_queue.corrections()["corrections"] == []


def test_stale_catalog_candidate_cannot_confirm_or_create_learning(monkeypatch, tmp_path):
    fake = _Orchestrator(tmp_path / "learning")
    monkeypatch.setattr(server, "orchestrator", fake)
    request = server.RecognitionCatalogSelectionRequest(
        state_id="previous-card",
        candidate={
            "id": "correct-card",
            "collector_number": "029/084",
            "language": "Simplified Chinese",
        },
    )

    try:
        asyncio.run(server.confirm_recognition_catalog_candidate(request))
    except server.HTTPException as exc:
        assert exc.status_code == 409
        assert "Recognition changed" in str(exc.detail)
    else:
        raise AssertionError("stale catalog selection unexpectedly succeeded")

    assert fake.confirmed is None
    assert fake.learning_queue.corrections()["corrections"] == []


def test_catalog_correction_requires_a_stable_identity(monkeypatch, tmp_path):
    fake = _Orchestrator(tmp_path / "learning")
    monkeypatch.setattr(server, "orchestrator", fake)
    request = server.RecognitionCatalogSelectionRequest(
        state_id="state-review-1",
        candidate={"name": "Unstable search result"},
    )

    try:
        asyncio.run(server.confirm_recognition_catalog_candidate(request))
    except server.HTTPException as exc:
        assert exc.status_code == 422
        assert "stable identity" in str(exc.detail)
    else:
        raise AssertionError("identity-free catalog selection unexpectedly succeeded")

    assert fake.confirmed is None
    assert fake.learning_queue.corrections()["corrections"] == []


def test_learning_correction_audit_survives_disk_round_trip(tmp_path):
    service = LearningQueueService(tmp_path)
    resolution = {
        "version": 1,
        "state_id": "state-review-1",
        "observed_identity": {"collector_number": "029/084"},
        "selected_identity": {"id": "correct-card"},
    }
    saved = service.add_correction(
        fingerprint="0123456789abcdef",
        candidate={"id": "correct-card"},
        state_id="state-review-1",
        resolution=resolution,
    )

    path = tmp_path / f"correction-{saved['correction']['id']}.json"
    assert json.loads(path.read_text(encoding="utf-8"))["resolution"] == resolution
    assert service.corrections()["corrections"][0]["resolution"] == resolution


def test_recent_pull_persists_operator_resolution(tmp_path):
    archive = tmp_path / "sessions"
    service = SessionService(archive)
    resolution = {
        "version": 1,
        "selection_source": "ranked_candidate",
        "prior_conflicts": [{"field": "language"}],
    }
    service.add_card({
        "card_name": "Card 029/084",
        "rarity": "C",
        "confidence": 0.9,
        "collector_number": "029/084",
        "language": "Simplified Chinese",
        "operator_resolution": resolution,
        "recognition_signature": "operator-review-card",
    })

    restored = SessionService(archive)
    assert restored.recent_cards(1)[0]["operator_resolution"] == resolution


def test_recent_scans_label_operator_corrections_without_mutating_live_state():
    root = Path(__file__).resolve().parents[1]
    script = (root / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
    recent = script.split("function renderUI4RecentScanDetail", 1)[1].split(
        "async function loadUI4RecentScans", 1
    )[0]
    assert 'resolution.textContent="Operator-corrected identity"' in recent
    assert 'resolution.textContent="Operator corrected"' in recent
    assert "resolution.hidden=!card.operator_resolution" in recent
    assert "loadRecognition(" not in recent
    assert "lastRecognitionGeneration" not in recent
    assert "lastRecognitionRevision" not in recent
