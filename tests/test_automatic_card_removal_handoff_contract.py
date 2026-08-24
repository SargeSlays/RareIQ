from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_auto_clear_only_arms_after_completed_decision():
    assert '!["approved","rejected"].includes(handoff)' in JS
    assert "!cardRemovalSettings.enabled" in JS
    assert "cardRemovalClearPending" in JS
    assert "function observeCompletedCardRemoval(snapshot={})" in JS
    assert "observeCompletedCardRemoval(context.snapshot||{})" in JS


def test_auto_clear_requires_authoritative_stable_absence():
    assert "snapshot?.card_present===true" in JS
    assert "normal:{polls:3,ms:650" in JS
    assert "const preset=CARD_REMOVAL_PRESETS[cardRemovalSettings.sensitivity]" in JS
    assert "cardRemovalMissingPolls>=preset.polls" in JS
    assert "now-cardRemovalMissingSince>=preset.ms" in JS


def test_auto_clear_is_single_flight_and_reuses_manual_clear_path():
    assert "cardRemovalClearPending=true" in JS
    assert "requestNextRecognition()" in JS
    assert "cardRemovalClearPending=false" in JS
    assert 'notify("Next Card Ready"' in JS


def test_operator_can_see_auto_clear_is_armed():
    removal_css = CSS[CSS.index("Automatic removal arming feedback") :]
    assert 'content:" · AUTO"' in removal_css
    assert 'content:" · AUTO CLEAR ARMED"' in removal_css
    assert "html[data-theme=light]" in removal_css
