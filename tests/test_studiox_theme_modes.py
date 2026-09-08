from pathlib import Path

CONTROL=Path("rareiq/web/static/control.html").read_text(encoding="utf-8")
STUDIO=Path("rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS=Path("rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")

def test_theme_selector_exposes_five_skins_and_preserves_legacy_migration():
    for choice in ("ignite","afterdark","voltage","ember","daylight"):
        assert f'data-theme-choice="{choice}"' in CONTROL
    appearance=Path("rareiq/web/static/studio_appearance.js").read_text(encoding="utf-8")
    assert 'rareiq.studiox.theme.v1' in appearance
    assert CONTROL.index('/static/studio_appearance.js?v=') < CONTROL.index('/static/studiox.css?v=')
    assert 'const STUDIOX_THEME_KEY=' in STUDIO
    assert 'function applyStudioTheme(' in STUDIO
    assert 'prefers-color-scheme: light' in appearance
    assert 'window.StudioAppearance' in STUDIO

def test_every_studiox_entry_loads_the_shared_appearance_dependency_first():
    for page in Path("rareiq/web/static").glob("*.html"):
        text=page.read_text(encoding="utf-8")
        if 'src="/static/studiox.js' in text:
            assert '/static/studio_appearance.js?v=' in text, page.name
            assert text.index('/static/studio_appearance.js?v=') < text.index('src="/static/studiox.js'), page.name

def test_light_theme_covers_shell_and_operational_surfaces():
    assert 'html[data-theme="light"] body.studiox-ui4' in CSS
    for surface in (".ui4-navigation-rail",".camera-workspace",".inspector",".collection-ledger",".inventory-manager"):
        assert surface in CSS

def test_system_following_and_reset_remain_separate_from_skin_radios():
    assert 'id="studioFollowSystem"' in CONTROL
    assert 'id="studioAppearanceReset"' in CONTROL
    assert 'role="radiogroup" aria-label="Operator skin"' in CONTROL
