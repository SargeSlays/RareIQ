from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "rareiq" / "web" / "static"
HTML = (STATIC / "control.html").read_text(encoding="utf-8-sig")
CSS = (STATIC / "studiox_update15.css").read_text(encoding="utf-8-sig")


def test_light_intelligence_widgets_override_late_dark_gradient() -> None:
    selector = 'html[data-theme="light"] body.studiox-ui4.studiox-premium :is(.premium-card-context-header,.recognition-signal-panel,.studiox-widget)'
    assert selector in CSS
    section = CSS[CSS.index(selector) : CSS.index("html[data-theme=\"light\"] body.studiox-ui4.studiox-premium .studiox-widget-header")]
    assert "background:#f8fbfc!important" in section
    assert "border-color:#c8dce4!important" in section


def test_light_widget_headers_and_empty_states_remain_readable() -> None:
    assert '.studiox-widget-grid>.studiox-widget[data-studiox-widget]' in CSS
    assert 'html[data-theme="light"] body.studiox-ui4.studiox-premium .studiox-widget-focus' in CSS
    assert "background:transparent!important" in CSS
    assert "color:#1a303d!important" in CSS
    assert '.studiox-widget :is(.studiox-grade-state,.studiox-widget-empty-state)' in CSS
    assert "background:#eef5f7!important" in CSS


def test_intelligence_widget_contracts_remain_unique() -> None:
    for label in (
        "Identity intelligence",
        "Rare Intelligence character and species profile",
        "Estimated AI condition analysis",
        "Card details",
    ):
        assert HTML.count(f'aria-label="{label}"') == 1
