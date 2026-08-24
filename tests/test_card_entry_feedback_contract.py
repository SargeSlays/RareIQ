from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
STYLES = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_card_entry_feedback_only_fires_on_absent_to_present_transition():
    assert "let lastObservedCardPresent=null" in SCRIPT
    assert "function observeCardEntryFeedback(snapshot={})" in SCRIPT
    assert "present&&lastObservedCardPresent===false" in SCRIPT
    assert '["approved","rejected"].includes(document.body.dataset.cardHandoff)' in SCRIPT
    assert 'document.body.dataset.cardEntry="detected"' in SCRIPT
    assert "observeCardEntryFeedback(context.snapshot||{})" in SCRIPT


def test_card_entry_clears_handoff_ui_without_touching_recognition():
    observer = SCRIPT.split("function observeCardEntryFeedback", 1)[1].split("function beginCardHandoff", 1)[0]
    assert "delete document.body.dataset.cardHandoff" in observer
    assert 'renderCardRemovalProgress(0,"Waiting for removal",false)' in observer
    assert "requestNextRecognition" not in observer
    assert "api(" not in observer


def test_card_entry_motion_is_brief_and_accessible():
    assert '[data-card-entry="detected"] .scan-zone' in STYLES
    assert "@keyframes card-entry-zone-pulse" in STYLES
    assert "@media(prefers-reduced-motion:reduce)" in STYLES
