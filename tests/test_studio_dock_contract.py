from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / 'rareiq/web/static'


def test_dock_visibility_integrates_with_existing_broadcast_navigation():
    js = (STATIC / 'studiox.js').read_text(encoding='utf-8')
    assert 'workspace._studioDocks?.setView(view)' in js
    assert 'window.ProducerStudioDocks?.init(workspace)' in js
    html = (STATIC / 'control.html').read_text(encoding='utf-8')
    assert html.index('/static/studio_docks.js') < html.index('/static/studiox.js')


def test_docks_keep_one_controller_and_original_tool_nodes():
    js = (STATIC / 'studio_docks.js').read_text(encoding='utf-8')
    for unsafe in ('cloneNode(', 'innerHTML', 'window.open(', 'fetch(', 'setInterval('):
        assert unsafe not in js
    assert 'wrapper.append(header,item.panel)' in js
    assert 'center.append(stage)' in js
    assert 'catch{status.textContent=' in js


def test_dock_stage_resets_legacy_wide_screen_grid_placement():
    css = (STATIC / "studio_shell.css").read_text(encoding="utf-8")
    assert ".studio-dock-center .production-switcher-shell > * { grid-column:1!important; grid-row:auto!important; }" in css


def test_hidden_workspace_resize_does_not_erase_floating_position():
    js = (STATIC / "studio_docks.js").read_text(encoding="utf-8")
    assert 'if(view!=="live"||item.wrapper.hidden||!bounds.width||!bounds.height)return;' in js


def test_parent_lockup_retains_height_when_css_image_changes():
    css = (STATIC / "studio_shell.css").read_text(encoding="utf-8")
    assert "width:208px !important; min-width:208px !important; height:59px !important" in css
