from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "rareiq" / "web" / "static"
HTML = (STATIC / "control.html").read_text(encoding="utf-8-sig")
CSS = (STATIC / "studiox_update15.css").read_text(encoding="utf-8-sig")


def test_light_voice_mod_sliders_use_readable_theme_surfaces() -> None:
    assert 'html[data-theme="light"] body.studiox-ui4 .voice-mod-sliders label' in CSS
    assert "background:#fff" in CSS
    assert "color:#4f6a77" in CSS
    assert 'html[data-theme="light"] body.studiox-ui4 .voice-mod-sliders b' in CSS
    assert "color:#087e9d" in CSS


def test_light_voice_mod_supporting_panels_match_the_active_theme() -> None:
    assert 'html[data-theme="light"] body.studiox-ui4 .voice-mod-monitor' in CSS
    assert "background:#edf9f5" in CSS
    assert 'html[data-theme="light"] body.studiox-ui4 .voice-mod-route-note' in CSS
    assert "background:#f4f1ff" in CSS


def test_voice_mod_processing_controls_and_handlers_remain_unique() -> None:
    for element_id in (
        "voiceModStart",
        "voiceModInput",
        "voiceModPreset",
        "voiceModGain",
        "voiceModMix",
        "voiceModOutput",
        "voiceModMonitor",
        "voiceModStop",
    ):
        assert HTML.count(f'id="{element_id}"') == 1
