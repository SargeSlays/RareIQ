from pathlib import Path
import re

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


def test_parent_lockup_clears_inherited_minimum_and_preserves_narrow_mark():
    css = (STATIC / "studio_shell.css").read_text(encoding="utf-8")
    rules = re.findall(r'\.appbar \.brand-lockup-image \{([^}]+)\}', css)
    assert len(rules) == 2
    desktop, narrow = [dict(part.strip().split(':', 1) for part in rule.split(';') if part.strip()) for rule in rules]
    # The legacy 208px minimum stretched the 2400:680 asset after height became 44px.
    assert desktop['width'] == 'auto!important'
    assert desktop['min-width'] == '0!important'
    assert desktop['object-fit'] == 'contain!important'
    assert desktop['max-width'] == '100%!important'
    # The final height owner must also leave the compact SVG square.
    assert narrow['width'] == narrow['height'] == narrow['max-height'] == '32px!important'
    assert '@container studio-content (max-width:760px)' in css[css.index(rules[0]):css.index(rules[1])]


def test_input_picture_and_empty_state_use_the_same_responsive_video_geometry():
    css = (STATIC / 'studio_shell.css').read_text(encoding='utf-8')
    for selector in ('.production-inputs img', '.production-input-empty'):
        rule = re.findall(re.escape(selector) + r' \{([^}]+)\}', css)[-1]
        properties = dict(part.strip().split(':', 1) for part in rule.split(';') if part.strip())
        assert properties['aspect-ratio'] == '16/9!important'
        assert properties['height'] == 'auto!important'
        assert properties['max-height'] == 'none!important'
        assert properties['width'] == 'min(100%,320px)!important'
    # A later short-screen override must not flatten the same pictures back to 40px.
    assert '.production-inputs :is(img,.production-input-empty) { height:40px' not in css
    assert 'grid-template-rows:auto 76px' not in css
    assert 'grid-template-rows:auto 40px' not in css


def test_input_tallies_reserve_space_beside_camera_labels():
    css = (STATIC / 'studio_shell.css').read_text(encoding='utf-8')
    label = re.search(r'\.production-inputs button:is\(\.is-program,\.is-preview\) > strong \{([^}]+)\}', css).group(1)
    # Cover the badge plus a readable gap even when compact cards use 7px padding.
    assert 'padding-inline-end:40px!important' in label


def test_desktop_greenroom_has_a_full_width_dock_and_side_by_side_chat():
    shell = (STATIC / 'studio_shell.css').read_text(encoding='utf-8')
    room = (STATIC / 'greenroom_controls.css').read_text(encoding='utf-8')
    assert '.studio-dock-bottom > [data-studio-tool="production-greenroom"] { grid-column:1/-1!important; grid-row:1!important;' in shell
    assert '@container greenroom (min-width:900px)' in room
    assert '.greenroom-chat-slot { grid-column:2; grid-row:1;' in room
    assert 'position:sticky; top:100px' in room
    assert 'grid-template-columns:repeat(3,minmax(0,1fr))' in room
