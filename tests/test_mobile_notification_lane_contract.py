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
    assert "left:auto!important" in contract
    assert "right:8px!important" in contract
    assert "width:min(260px,calc(100vw - 16px))!important" in contract
    assert "max-width:260px!important" in contract
    assert "pointer-events:none!important" in contract


def test_mobile_notifications_are_compact_without_removing_copy() -> None:
    contract = notification_contract()
    assert "grid-template-columns:24px minmax(0,1fr) 24px!important" in contract
    assert "min-height:38px!important" in contract
    assert ".notification-icon{width:24px!important;height:24px!important}" in contract
    assert ".notification-copy strong{" in contract
    assert ".notification-copy span{" in contract
    assert HTML.count('id="notificationStack"') == 1
    assert 'role="region" aria-label="Operator notifications" aria-live="polite"' in HTML


def test_short_landscape_notifications_sit_directly_above_the_operator_deck() -> None:
    contract = notification_contract()
    assert '@media(max-width:959px) and (orientation:landscape) and (max-height:600px)' in contract
    assert "bottom:calc(118px + env(safe-area-inset-bottom,0px))!important" in contract
    assert "max-width:280px!important" in contract


def test_notifications_are_bounded_deduplicated_and_operator_dismissible() -> None:
    assert 'node.className=`riq-notification ${safeType}`' in JS
    assert "const STUDIOX_NOTIFICATION_LIMIT=4" in JS
    assert "const STUDIOX_NOTIFICATION_DEDUPE_MS=1500" in JS
    assert "while(stack.children.length>=STUDIOX_NOTIFICATION_LIMIT)" in JS
    assert 'dismiss.className="notification-dismiss"' in JS
    assert 'dismiss.setAttribute("aria-label",`Dismiss ${safeTitle} notification`)' in JS
    assert 'node.addEventListener("focusin",()=>clearTimeout(node._hideTimer))' in JS


def test_notification_copy_is_written_as_text_not_interpolated_html() -> None:
    section = JS[JS.index("function notify("):JS.index("function updateAiPulse", JS.index("function notify("))]
    assert "heading.textContent=safeTitle" in section
    assert "description.textContent=safeDetail" in section
    assert "node.innerHTML" not in section
    assert 'node.setAttribute("role",safeType==="error"?"alert":"status")' in section
