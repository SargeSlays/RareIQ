from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_settings_expose_toggle_and_adaptive_sensitivity_presets():
    assert 'id="automaticCardRemovalEnabled"' in HTML
    assert 'id="automaticCardRemovalSensitivity"' in HTML
    for value in ("adaptive", "safe", "normal", "fast"):
        assert f'value="{value}"' in HTML


def test_removal_preferences_persist_with_conservative_defaults():
    assert 'CARD_REMOVAL_SETTINGS_KEY="rareiq.automaticCardRemoval.v1"' in JS
    assert "safe:{polls:5,ms:1200" in JS
    assert "normal:{polls:3,ms:650" in JS
    assert "fast:{polls:2,ms:300" in JS
    assert "localStorage.setItem(CARD_REMOVAL_SETTINGS_KEY" in JS
    assert "saved.enabled!==false" in JS


def test_adaptive_timing_is_bounded_persistent_and_requires_evidence():
    assert 'CARD_HANDOFF_TIMING_KEY="rareiq.cardHandoffTimings.v1"' in JS
    assert "stats.count<4?CARD_REMOVAL_PRESETS.normal" in JS
    assert "stats.median<=800?CARD_REMOVAL_PRESETS.fast" in JS
    assert "stats.median<=1800?CARD_REMOVAL_PRESETS.normal:CARD_REMOVAL_PRESETS.safe" in JS
    assert "rows.slice(-30)" in JS
    assert "value<150||value>15000" in JS
    assert "recordCardHandoffTiming(elapsedMs,method)" in JS


def test_removal_observer_uses_operator_selected_preset_and_toggle():
    assert "if(!cardRemovalSettings.enabled||" in JS
    assert "const preset=CARD_REMOVAL_PRESETS[cardRemovalSettings.sensitivity]" in JS
    assert "cardRemovalMissingPolls>=preset.polls" in JS
    assert "now-cardRemovalMissingSince>=preset.ms" in JS


def test_settings_are_responsive_and_themed():
    settings_css = CSS[CSS.index("Card handoff operator settings") :]
    assert 'data-auto-card-removal="off"' in settings_css
    assert "html[data-theme=light]" in settings_css
    assert "@media(max-width:900px)" in settings_css
    assert "@media(max-width:560px)" in settings_css
