from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "rareiq" / "web" / "static"
HTML = (STATIC / "control.html").read_text(encoding="utf-8-sig")
CSS = (STATIC / "studiox_command_deck.css").read_text(encoding="utf-8-sig")


def test_light_voice_mod_sliders_use_readable_theme_surfaces() -> None:
    voice_mod = CSS[CSS.index("/* Voice Mod */") : CSS.index("/* Camera FX */")]
    assert '.workspace[data-workspace="voice-mod"] .voice-mod-sliders label' in voice_mod
    assert "background: var(--sx-surface-muted)" in voice_mod
    assert "color: var(--sx-text-muted)" in voice_mod
    assert '.workspace[data-workspace="voice-mod"] .voice-mod-sliders b' in voice_mod
    assert "color: var(--sx-accent)" in voice_mod


def test_light_voice_mod_supporting_panels_match_the_active_theme() -> None:
    voice_mod = CSS[CSS.index("/* Voice Mod */") : CSS.index("/* Camera FX */")]
    assert '.workspace[data-workspace="voice-mod"] .voice-mod-monitor' in voice_mod
    assert "background: var(--sx-accent-faint)" in voice_mod
    assert '.workspace[data-workspace="voice-mod"] .voice-mod-route-note' in voice_mod
    assert "background: var(--sx-surface-muted)" in voice_mod


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


def test_voice_mod_shell_stays_content_sized_and_stacks_responsively() -> None:
    voice_mod = CSS[CSS.index("/* Voice Mod */") : CSS.index("/* Camera FX */")]
    assert "min-height: 0 !important" in voice_mod
    assert "grid-template-rows: auto auto !important" in voice_mod
    assert "grid-template-columns: minmax(0, 1fr) !important" in voice_mod
