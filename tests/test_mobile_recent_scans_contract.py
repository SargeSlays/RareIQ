from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8-sig")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8-sig")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8-sig")


def mobile_history_contract() -> str:
    start = CSS.index("/* Mobile Recent Scans is a bounded")
    end = CSS.index("/* Update 6.8.9", start)
    return CSS[start:end]


def test_mobile_recent_scans_is_bounded_above_the_operator_deck() -> None:
    contract = mobile_history_contract()
    assert ':has(.inspector[data-primary-view="recent"])' in contract
    assert "height:calc(100svh - 170px)!important" in contract
    assert 'inspector[data-primary-view="recent"]' in contract
    assert "height:100%!important" in contract
    assert "overflow-y:auto!important" in contract
    assert "overscroll-behavior:contain!important" in contract


def test_mobile_recent_scan_thumbnails_are_clipped_and_geometry_safe() -> None:
    contract = mobile_history_contract()
    assert ".ui4-history-thumb{" in contract
    assert "width:40px!important" in contract
    assert "height:56px!important" in contract
    assert "overflow:hidden!important" in contract
    assert ".ui4-history-thumb img{" in contract
    assert "max-width:100%!important" in contract
    assert "max-height:100%!important" in contract
    assert "object-fit:contain!important" in contract


def test_mobile_recent_scan_identity_and_result_are_separate_columns() -> None:
    contract = mobile_history_contract()
    assert ".ui4-history-identity{" in contract
    assert "display:grid!important" in contract
    assert "align-content:center!important" in contract
    assert ".ui4-history-result{" in contract
    assert "justify-items:end!important" in contract


def test_mobile_recent_scans_reuses_existing_history_and_return_to_live_flow() -> None:
    assert HTML.count('id="mobileOperatorViewScans"') == 1
    assert HTML.count('id="mobileOperatorHistoryLive"') == 1
    assert 'api("/api/recent-pulls?limit=20")' in JS
    assert 'setMobileOperatorDestination("recent-scans")' in JS
    assert '$("mobileOperatorHistoryLive")?.addEventListener("click",()=>setMobileOperatorDestination("card"))' in JS
