from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8-sig")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8-sig")


def test_live_mobile_deck_does_not_cover_other_workspaces() -> None:
    assert '[data-ui4-workspace]:not([data-ui4-workspace="live"]) .ui4-mobile-action-region{display:none!important}' in CSS
    assert '[data-ui4-workspace]:not([data-ui4-workspace="live"]){padding-bottom:calc(70px + env(safe-area-inset-bottom,0px))!important}' in CSS
    assert '[data-ui4-workspace]:not([data-ui4-workspace="live"]) .recognition-workflow-prompt{display:none!important}' in CSS


def test_non_live_mobile_workspaces_restore_center_content_and_hide_inspector() -> None:
    assert '[data-ui4-workspace="live"][data-mobile-operator-view="card"] .ui4-center-column{display:none!important}' in CSS
    assert '[data-ui4-workspace]:not([data-ui4-workspace="live"]) .ui4-center-column{display:grid!important;grid-template-rows:minmax(0,1fr)!important;width:100%!important}' in CSS
    assert '[data-ui4-workspace]:not([data-ui4-workspace="live"]) .ui4-command-bar{display:none!important}' in CSS
    assert '[data-ui4-workspace]:not([data-ui4-workspace="live"]) .ui4-inspector-column{display:none!important}' in CSS


def test_switching_away_from_live_closes_mobile_status_sheet() -> None:
    section = JS[JS.index("function switchWorkspace") : JS.index("function voiceModPreferences")]
    assert 'document.body.dataset.ui4Workspace=name' in section
    assert 'if(name!=="live")setUI4HealthOpen(false)' in section


def test_live_operator_controls_remain_available_on_live_workspace() -> None:
    assert 'body.studiox-ui4.studiox-premium .ui4-mobile-action-region{display:none!important}' in CSS
    assert '@media(max-width:959px)' in CSS
    mobile = CSS[CSS.index("@media(max-width:959px)") :]
    assert '.ui4-mobile-action-region{' in mobile
    assert 'display:grid!important' in mobile
