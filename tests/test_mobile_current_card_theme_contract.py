from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "rareiq" / "web" / "static"
HTML = (STATIC / "control.html").read_text(encoding="utf-8-sig")
CSS = (STATIC / "studiox_update15.css").read_text(encoding="utf-8-sig")


def test_light_current_card_and_signal_panels_use_readable_surfaces() -> None:
    selector = 'html[data-theme="light"] body.studiox-ui4.studiox-premium :is(.premium-card-context-header,.recognition-signal-panel)'
    assert selector in CSS
    section = CSS[CSS.index(selector) : CSS.index("body.studiox-ui4.studiox-premium .recognition-signal-title", CSS.index(selector))]
    assert "background:#f8fbfc!important" in section
    assert "border-color:#c8dce4!important" in section


def test_light_signal_tracks_keep_contrast_without_changing_values() -> None:
    selector = 'html[data-theme="light"] body.studiox-ui4.studiox-premium .recognition-signal-panel .signal .bar'
    assert selector in CSS
    assert "background:#dce8ed!important" in CSS
    assert "#confidenceRingValue" not in CSS


def test_current_card_and_signal_contract_ids_remain_unique() -> None:
    for element_id in (
        "recognitionSignalPanel",
        "confidenceRing",
        "confidenceRingValue",
        "cardName",
        "cardArt",
    ):
        assert HTML.count(f'id="{element_id}"') == 1
