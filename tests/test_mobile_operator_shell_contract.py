from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8-sig")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8-sig")


def mobile_shell_contract() -> str:
    return CSS[CSS.rindex("mobile operator shell foundation") :]


def test_studiox_stylesheet_has_balanced_rule_blocks() -> None:
    assert CSS.count("{") == CSS.count("}")


def test_mobile_shell_keeps_primary_workspace_above_navigation() -> None:
    contract = mobile_shell_contract()
    assert "@media(max-width:959px)" in contract
    assert "display:flex!important" in contract
    assert "flex-direction:column!important" in contract
    assert "position:fixed!important" in contract
    assert "bottom:0!important" in contract
    assert "overflow-x:auto!important" in contract
    assert "order:1!important" in contract
    assert "order:2!important" in contract


def test_mobile_command_surface_is_sticky_and_horizontally_scrollable() -> None:
    contract = mobile_shell_contract()
    assert "position:sticky!important" in contract
    assert "grid-template-rows:44px 64px!important" in contract
    assert "height:108px!important" in contract
    assert ".premium-command-bar" in contract
    assert "height:64px!important" in contract


def test_mobile_single_camera_preserves_full_frame_geometry() -> None:
    contract = mobile_shell_contract()
    assert 'data-camera-layout="single"' in contract
    assert "aspect-ratio:16/9!important" in contract
    assert "height:auto!important" in contract
    assert "object-fit:cover" not in contract
    assert HTML.count('id="cameraFeed"') == 1


def test_closed_mobile_diagnostics_do_not_cover_the_camera() -> None:
    contract = mobile_shell_contract()
    assert ".camera-workspace>.ui4-diagnostics-drawer" in contract
    assert "display:none!important" in contract
    assert ".ui4-diagnostics-drawer.open" in contract
    assert "position:fixed!important" in contract


def test_mobile_camera_toolbar_scrolls_instead_of_overlapping() -> None:
    contract = mobile_shell_contract()
    assert ".camera-workspace-toolbar" in contract
    assert "overflow-x:auto!important" in contract
    assert ".camera-view-overflow-panel" in contract
    assert "width:max-content!important" in contract


def test_mobile_shell_preserves_all_navigation_and_action_handlers() -> None:
    assert HTML.count("shell=6.8.9-mobile-shell12") == 2
    assert HTML.count('class="nav-button') == 11
    for handler in (
        "selectCamera()",
        "captureRecognitionMode()",
        "toggleAutoCapture()",
        "openCameraPopout()",
    ):
        assert handler in HTML
