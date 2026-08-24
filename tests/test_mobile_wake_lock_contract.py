from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "rareiq" / "web" / "static"
HTML = (STATIC / "control.html").read_text(encoding="utf-8-sig")
SCRIPT = (STATIC / "studiox.js").read_text(encoding="utf-8-sig")


def test_wake_lock_is_unique_and_off_by_default() -> None:
    assert HTML.count('id="mobileWakeLockEnabled"') == 1
    assert HTML.count('id="mobileWakeLockStatus"') == 1
    element = HTML.split('id="mobileWakeLockEnabled"', 1)[0].rsplit("<input", 1)[1]
    assert "checked" not in element


def test_wake_lock_requires_an_explicit_toggle_action() -> None:
    init = SCRIPT[SCRIPT.index("function initializeMobileWakeLock") : SCRIPT.index("let mobileAccessUrl")]
    assert 'addEventListener("change"' in init
    assert "event.target.checked===true" in init
    assert "requestMobileWakeLock()" in init
    assert 'navigator.wakeLock.request("screen")' in SCRIPT
    assert "requestMobileWakeLock();" not in SCRIPT[: SCRIPT.index("function initializeMobileWakeLock")]


def test_wake_lock_releases_while_hidden_and_reacquires_when_visible() -> None:
    init = SCRIPT[SCRIPT.index("function initializeMobileWakeLock") : SCRIPT.index("let mobileAccessUrl")]
    assert 'document.addEventListener("visibilitychange"' in init
    assert 'if(document.hidden===true)releaseMobileWakeLock();else requestMobileWakeLock()' in init
    assert "setInterval" not in init


def test_unsupported_and_denied_states_are_truthful() -> None:
    assert 'typeof navigator.wakeLock?.request==="function"' in SCRIPT
    assert 'toggle.disabled=!supported' in SCRIPT
    assert 'unsupported:"Unavailable in this browser"' in SCRIPT
    assert 'notify("Screen Awake Unavailable"' in SCRIPT
