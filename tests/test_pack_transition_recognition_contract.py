from pathlib import Path


SOURCE = (
    Path(__file__).resolve().parents[1]
    / "rareiq/services/recognition_service.py"
).read_text(encoding="utf-8")


def test_transition_learning_only_receives_locked_recognition_results():
    block = SOURCE.split(
        'if payload.get("recognition_locked") and payload.get("candidates"):', 1
    )[1].split("except Exception as exc:", 1)[0]
    assert "observe_verified_card(" in block
    assert "verified_number," in block
    assert 'payload.get("overall_confidence")' in block
    assert 'payload.get("collector_number")' in block
    assert 'payload["candidates"][0].get("collector_number")' in block
    assert 'payload["artwork_index"]["status"] = self.artwork_index.status()' in block
