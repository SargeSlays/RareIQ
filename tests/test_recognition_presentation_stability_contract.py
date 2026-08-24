from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")


def test_intermediate_recognition_states_have_short_monotonic_smoothing():
    assert "function stabilizeRecognitionPresentation(presentation,snapshot={})" in SCRIPT
    assert 'rank={detecting:1,scanning:2,"candidate-found":3,verifying:4}' in SCRIPT
    assert "rank[next.key]<rank[previous.key]" in SCRIPT
    assert "changedAt<480" in SCRIPT


def test_terminal_states_and_empty_frame_bypass_smoothing():
    stabilizer = SCRIPT.split("function stabilizeRecognitionPresentation", 1)[1].split("async function loadRecognition", 1)[0]
    for state in ("ready", "exact-match", "review-needed", "error"):
        assert f'"{state}"' in stabilizer
    assert "if(!present||" in stabilizer


def test_smoothed_presentation_feeds_the_shared_context_and_resets():
    assert "const presentation=stabilizeRecognitionPresentation(deriveRecognitionPresentation(" in SCRIPT
    reset = SCRIPT.split('function resetRecognitionPresentation(reason="reset")', 1)[1].split("async function requestNextRecognition", 1)[0]
    assert 'recognitionPresentationMemory={key:"ready",presentation:null,changedAt:0}' in reset
