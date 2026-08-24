from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_approval_and_rejection_enter_explicit_card_removal_state():
    assert 'beginCardHandoff("approved")' in JS
    assert 'beginCardHandoff("rejected")' in JS
    assert '"Remove card from the scan zone"' in JS
    assert '"RareIQ will hold this result until the card leaves view."' in JS


def test_next_clear_wraps_existing_endpoint_with_ready_for_next_feedback():
    assert 'beginCardHandoff("cleared")' in JS
    assert 'fetch("/api/recognition/clear"' in JS
    assert "completeCardHandoff();" in JS
    assert '"Present next card"' in JS
    assert '"Place the next card inside the scan zone."' in JS


def test_handoff_states_are_visually_distinct_and_accessible():
    handoff_css = CSS[CSS.index("Card handoff feedback") :]
    for state in ("approved", "rejected", "cleared", "ready"):
        assert f'data-card-handoff="{state}"' in handoff_css
    assert "html[data-theme=light]" in handoff_css
    assert "@media(prefers-reduced-motion:reduce)" in handoff_css
