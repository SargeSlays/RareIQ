from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_signal_rail_keeps_all_live_recognition_values():
    for element_id in (
        "confidenceRingValue",
        "confidenceRingLabel",
        "visionValue",
        "ocrValue",
        "collectorValue",
        "fusionValue",
    ):
        assert f'id="{element_id}"' in HTML


def test_signal_rail_is_single_row_and_space_efficient():
    marker = "Recognition status rail"
    rail_css = CSS[CSS.index(marker) :]
    assert "grid-template-columns:auto 46px minmax(0,1fr)" in rail_css
    assert "grid-template-rows:1fr" in rail_css
    assert "grid-template-columns:repeat(4,minmax(54px,1fr))" in rail_css
    assert "margin:8px 0" in rail_css
    assert "padding:8px 10px" in rail_css


def test_signal_rail_has_mobile_and_light_theme_treatment():
    marker = "Recognition status rail"
    rail_css = CSS[CSS.index(marker) :]
    assert "html[data-theme=light]" in rail_css
    assert "@media(max-width:520px)" in rail_css
    assert "grid-template-columns:repeat(2,minmax(0,1fr))" in rail_css
