from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8-sig")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8-sig")


def full_shell_contract() -> str:
    start = CSS.index("/* Mobile full-shell workspaces own")
    end = CSS.index("/* Update 6.8.9", start)
    return CSS[start:end]


def test_all_active_non_live_full_shells_use_one_content_column() -> None:
    contract = full_shell_contract()
    selector = '[data-ui4-workspace]:not([data-ui4-workspace="live"]) .workspace.active'
    assert f"{selector} .full-shell" in contract
    assert "grid-template-columns:minmax(0,1fr)!important" in contract
    assert f"{selector} .full-shell>.content" in contract
    assert "overflow-x:hidden!important" in contract


def test_all_active_non_live_side_rails_become_horizontal() -> None:
    contract = full_shell_contract()
    assert ".workspace.active .side-nav{" in contract
    assert "flex-direction:row!important" in contract
    assert "overflow-x:auto!important" in contract
    assert "overscroll-behavior-x:contain!important" in contract


def test_settings_mobile_access_and_install_controls_remain_unique() -> None:
    assert HTML.count('data-workspace="settings"') == 1
    for element_id in (
        "mobileAccessTitle",
        "mobileAccessSummary",
        "mobileInstallButton",
        "mobileInstallStatus",
        "mobileAccessRefresh",
    ):
        assert HTML.count(f'id="{element_id}"') == 1
