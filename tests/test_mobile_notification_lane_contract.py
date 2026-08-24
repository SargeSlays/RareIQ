from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8-sig")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8-sig")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8-sig")


def notification_contract() -> str:
    start = CSS.index("/* Mobile notifications sit above")
    end = CSS.index("/* Update 6.8.9", start)
    return CSS[start:end]


def test_mobile_notifications_use_a_bounded_lane_above_the_operator_deck() -> None:
    contract = notification_contract()
    assert ".notification-stack{" in contract
    assert "top:auto!important" in contract
    assert "bottom:calc(178px + env(safe-area-inset-bottom,0px))!important" in contract
    assert "left:8px!important" in contract
    assert "right:8px!important" in contract
    assert "max-width:374px!important" in contract


def test_mobile_notifications_are_compact_without_removing_copy() -> None:
    contract = notification_contract()
    assert "grid-template-columns:28px minmax(0,1fr)!important" in contract
    assert "min-height:44px!important" in contract
    assert ".notification-icon{width:28px!important;height:28px!important}" in contract
    assert ".notification-copy strong{" in contract
    assert ".notification-copy span{" in contract
    assert HTML.count('id="notificationStack"') == 1


def test_notification_creation_and_lifetime_are_unchanged() -> None:
    assert 'node.className=`riq-notification ${type}`' in JS
    assert "stack.appendChild(node)" in JS
    assert "},2800);" in JS
    assert "setTimeout(()=>node.remove(),3100)" in JS
