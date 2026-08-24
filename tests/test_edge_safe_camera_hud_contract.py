from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_camera_hud_preserves_live_state_elements_and_hides_duplicate_confidence():
    for element_id in ("cameraFeedStateShield", "unifiedScanStatus", "aiState", "aiDetail", "confidence"):
        assert f'id="{element_id}"' in HTML
    hud_css = CSS[CSS.index("Edge-safe camera HUD") :]
    assert ".premium-scan-status .camera-confidence{display:none!important}" in hud_css


def test_camera_status_is_compact_and_anchored_to_safe_edges():
    hud_css = CSS[CSS.index("Edge-safe camera HUD") :]
    assert "bottom:12px" in hud_css
    assert "left:12px" in hud_css
    assert "max-width:min(270px,calc(100% - 24px))" in hud_css
    assert ".camera-top-hud{display:none!important}" in hud_css
    assert ".brand-watermark" in hud_css


def test_camera_hud_supports_states_mobile_light_theme_and_reduced_motion():
    hud_css = CSS[CSS.index("Edge-safe camera HUD") :]
    assert 'data-presentation-state="exact-match"' in hud_css
    assert 'data-presentation-state="review-needed"' in hud_css
    assert "html[data-theme=light]" in hud_css
    assert "@media(max-width:620px)" in hud_css
    assert "@media(prefers-reduced-motion:reduce)" in hud_css
