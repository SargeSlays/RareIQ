from pathlib import Path

CONTROL=Path("rareiq/web/static/control.html").read_text(encoding="utf-8")
CSS=Path("rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")

def test_left_navigation_uses_accessible_app_icons():
    # Ten application launchers plus the separate theme control icon.
    assert CONTROL.count('class="nav-app-icon"') == 11
    for label in ("Live","Collection","Broadcast","Creator","Soundboard","Voice Mod","Camera Effects","AI Lab","Library","Settings"):
        assert f'aria-label="{label}"' in CONTROL
    assert "App-launcher navigation rail" in CSS
    assert ".nav-app-icon svg" in CSS

def test_launcher_and_command_bar_have_final_alignment_layer():
    assert 'content:"APPS"' in CSS
    assert "grid-template-columns:176px minmax(0,1fr)" in CSS
    assert ".brand-logo-image" in CSS
    assert ".premium-command-bar>.command-group" in CSS

def test_app_launcher_overrides_legacy_wide_desktop_rail():
    assert "--sx-app-rail-width:88px" in CSS
    assert "--sx-app-rail-width:68px" in CSS
    assert "width:var(--sx-app-rail-width)!important" in CSS
    assert "width:64px!important;max-width:64px!important" in CSS
