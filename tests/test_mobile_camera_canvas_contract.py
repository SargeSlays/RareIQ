from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8-sig")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8-sig")


def camera_canvas_contract() -> str:
    start = CSS.index("/* Camera-only mobile view owns")
    end = CSS.index("/* Mobile card inspector density", start)
    return CSS[start:end]


def test_camera_only_view_fills_the_space_above_the_operator_deck() -> None:
    contract = camera_canvas_contract()
    assert '[data-mobile-operator-view="camera"] .ui4-center-column' in contract
    assert "height:calc(100svh - 170px)!important" in contract
    assert "grid-template-rows:108px minmax(0,1fr)!important" in contract
    assert "align-content:stretch!important" in contract
    assert "overflow:hidden!important" in contract
    assert "background:#050d13!important" in contract
    assert "grid-template-rows:44px auto!important" in contract
    assert 'html[data-theme="light"]' in contract


def test_camera_media_remains_width_driven_sixteen_by_nine() -> None:
    contract = camera_canvas_contract()
    mobile_shell = CSS[CSS.index("mobile operator shell foundation") :]
    assert 'data-camera-layout="single"' in mobile_shell
    assert "height:auto!important" in mobile_shell
    assert "aspect-ratio:16/9!important" in mobile_shell
    assert ".camera-stage-inner" not in contract
    assert "object-fit" not in contract
    assert HTML.count('id="cameraFeed"') == 1


def test_camera_only_view_preserves_existing_mobile_actions() -> None:
    contract = camera_canvas_contract()
    assert '[data-mobile-operator-view="camera"] .camera-workspace-toolbar{display:none!important}' in contract
    for element_id in (
        "mobileOperatorCapture",
        "mobileOperatorReconnect",
        "mobileOperatorStatus",
        "mobileOperatorViewCamera",
    ):
        assert HTML.count(f'id="{element_id}"') == 1
