from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_workspace_and_recognition_controls_share_a_visual_cluster():
    assert HTML.count('data-command-cluster="recognition"') == 3
    assert 'class="command-group studiox-layout-control"' in HTML
    assert 'class="command-group studiox-recognition-mode-control"' in HTML
    assert 'class="command-group studiox-set-context-control"' in HTML


def test_command_deck_has_one_compact_authoritative_height():
    deck_css = CSS[CSS.index("Final compact command deck") :]
    assert ".ui4-command-bar{height:64px!important;min-height:64px!important" in deck_css
    assert "height:32px!important;min-height:32px!important" in deck_css
    assert "grid-template-columns:minmax(220px,1.35fr)" in deck_css
    assert "grid-template-columns:minmax(0,1fr) 104px" in deck_css


def test_command_deck_preserves_core_controls_and_responsive_treatment():
    for element_id in ("cameraSelect", "workspaceLayoutPreset", "recognitionModeSelect", "viewerModeSelect"):
        assert f'id="{element_id}"' in HTML
    deck_css = CSS[CSS.index("Final compact command deck") :]
    assert "html[data-theme=light]" in deck_css
    assert "@media(max-width:1320px)" in deck_css
    assert "@media(max-width:760px)" in deck_css
