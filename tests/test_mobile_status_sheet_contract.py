from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8-sig")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8-sig")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8-sig")


def mobile_shell() -> str:
    return CSS[CSS.rindex("mobile operator shell foundation") :]


def test_mobile_status_uses_existing_health_popover_and_trigger() -> None:
    assert HTML.count('id="mobileOperatorStatus"') == 1
    assert '$("mobileOperatorStatus")?.addEventListener("click",()=>setUI4HealthOpen(!ui4HealthOpen))' in JS
    assert 'healthPopover.className="ui4-health-popover"' in JS
    assert 'healthPopover.setAttribute("role","dialog")' in JS
    assert 'healthPopover.setAttribute("aria-label","System status and camera actions")' in JS


def test_mobile_health_popover_is_a_visible_safe_area_sheet() -> None:
    section = mobile_shell()
    assert ".ui4-health-popover{" in section
    assert "position:fixed!important" in section
    assert "top:116px!important" in section
    assert "bottom:calc(174px + env(safe-area-inset-bottom,0px))!important" in section
    assert ".ui4-health-popover.open{display:grid!important}" in section
    assert "overflow:auto!important" in section
    assert 'window.matchMedia("(max-width: 959px)").matches?document.body:document.querySelector(".ui4-command-bar")' in JS
    assert 'window.addEventListener("resize",mountHealthPopover,{passive:true})' in JS


def test_status_sheet_adds_no_health_poll_or_recovery_path() -> None:
    setter = JS[JS.index("function setUI4HealthOpen") : JS.index("function setUI4InspectorTab")]
    assert "setInterval" not in setter
    assert "fetch(" not in setter
    assert "/restart" not in setter


def test_short_landscape_status_sheet_uses_the_available_visual_height() -> None:
    landscape = CSS[CSS.index("short landscape operator mode") :]
    assert '.ui4-health-popover{top:6px!important;bottom:calc(116px + env(safe-area-inset-bottom,0px))!important}' in landscape
