from pathlib import Path


CSS = Path("rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_fullscreen_toolbar_has_a_column_for_every_control_group():
    fullscreen = CSS.split("/* Fullscreen desktop:", 1)[1]
    assert "minmax(260px,1.1fr)" in fullscreen
    assert "minmax(120px,.5fr)" in fullscreen
    assert "minmax(140px,.58fr)" in fullscreen
    assert "minmax(230px,.9fr)" in fullscreen
    assert "minmax(270px,1fr)" in fullscreen
    assert "grid-row:1!important" in fullscreen


def test_fullscreen_camera_fills_the_available_workspace_height():
    fullscreen = CSS.split("/* Fullscreen desktop:", 1)[1]
    assert '.camera-workspace[data-camera-layout="single"]{' in fullscreen
    assert "height:100%!important" in fullscreen
    assert "bottom:8px!important" in fullscreen
    assert "object-fit:cover!important" in fullscreen
