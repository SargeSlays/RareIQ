from pathlib import Path

CONTROL=Path("rareiq/web/static/control.html").read_text(encoding="utf-8")
STUDIO=Path("rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS=Path("rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")

def test_theme_selector_supports_dark_light_and_system():
    for choice in ("dark","light","system"):
        assert f'data-theme-choice="{choice}"' in CONTROL
    assert 'rareiq.studiox.theme.v1' in CONTROL
    assert 'const STUDIOX_THEME_KEY=' in STUDIO
    assert 'function applyStudioTheme(' in STUDIO
    assert 'prefers-color-scheme: light' in STUDIO

def test_light_theme_covers_shell_and_operational_surfaces():
    assert 'html[data-theme="light"] body.studiox-ui4' in CSS
    for surface in (".ui4-navigation-rail",".camera-workspace",".inspector",".collection-ledger",".inventory-manager"):
        assert surface in CSS
