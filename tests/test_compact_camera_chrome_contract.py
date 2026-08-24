from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_camera_view_controls_remain_persistently_visible():
    assert 'id="cameraViewOverflow"' in HTML
    assert 'class="camera-view-overflow-panel"' in HTML
    overflow = HTML[HTML.index('id="cameraViewOverflow"') : HTML.index('id="cameraSoundboardPads"')]
    assert 'id="cameraWorkspaceLayout"' in overflow
    assert 'id="workspaceDensityControl"' in overflow
    assert '<details class="camera-view-overflow"' not in HTML
    assert 'camera-view-overflow camera-view-persistent' in HTML
    assert ".camera-view-persistent>.camera-view-overflow-panel{position:static!important;display:flex!important" in CSS


def test_primary_camera_actions_and_identity_controls_remain_visible():
    assert 'id="cameraSoundboardPads"' in HTML
    assert 'id="manageCamerasButton"' in HTML
    assert 'id="cameraSlot1Source"' in HTML
    assert 'id="cameraSlot1Side"' in HTML


def test_camera_chrome_is_compact_responsive_and_themed():
    camera_css = CSS[CSS.index("Compact camera chrome") :]
    assert "--camera-toolbar-height:44px" in camera_css
    assert "--camera-tile-header-height:48px" in camera_css
    assert ".camera-view-overflow-panel" in camera_css
    assert "html[data-theme=light]" in camera_css
    assert "@media(max-width:760px)" in camera_css
