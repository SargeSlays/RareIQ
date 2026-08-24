from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "rareiq" / "web" / "static"
HTML = (STATIC / "control.html").read_text(encoding="utf-8-sig")
SCRIPT = (STATIC / "studiox.js").read_text(encoding="utf-8-sig")
CSS = (STATIC / "studiox_update15.css").read_text(encoding="utf-8-sig")


def test_connection_status_surface_is_accessible_and_unique() -> None:
    for element_id in (
        "serverConnectionBanner",
        "serverConnectionTitle",
        "serverConnectionDetail",
        "serverConnectionRetry",
    ):
        assert HTML.count(f'id="{element_id}"') == 1
    assert 'role="status"' in HTML
    assert 'aria-live="polite"' in HTML
    assert 'aria-atomic="true"' in HTML
    assert 'id="serverConnectionRetry" type="button" aria-busy="false"' in HTML


def test_connection_status_reuses_api_events_without_a_polling_loop() -> None:
    section = SCRIPT[SCRIPT.index("function initializeServerConnectionStatus") : SCRIPT.index("async function loadCameraManagerState")]
    assert '"rareiq:api-error"' in section
    assert '"rareiq:api-end"' in section
    assert 'window.addEventListener("offline"' in section
    assert 'window.addEventListener("online"' in section
    assert "setInterval" not in section


def test_retry_uses_existing_boot_ping_and_does_not_restart_the_server() -> None:
    section = SCRIPT[SCRIPT.index("async function retryServerConnection") : SCRIPT.index("function initializeServerConnectionStatus")]
    assert 'api("/api/boot/ping"' in section
    assert "if(serverConnectionRetryInFlight)return false" in section
    assert "serverConnectionRetryInFlight=true" in section
    assert "finally{" in section
    assert "serverConnectionRetryInFlight=false" in section
    assert 'if(navigator.onLine===false){setServerConnectionState("offline");return false;}' in section
    assert 'method:"POST"' not in section
    assert "/restart" not in section


def test_http_api_errors_do_not_claim_the_server_is_disconnected() -> None:
    section = SCRIPT[SCRIPT.index("function initializeServerConnectionStatus") : SCRIPT.index("async function loadCameraManagerState")]
    assert "event.detail?.error?.status" in section


def test_unrelated_api_success_cannot_finish_an_active_connection_probe() -> None:
    section = SCRIPT[SCRIPT.index("function initializeServerConnectionStatus") : SCRIPT.index("async function loadCameraManagerState")]
    assert '["offline","unreachable"].includes(serverConnectionState)' in section
    assert "!serverConnectionRetryInFlight" in section
    assert '["offline","unreachable","checking"]' not in section


def test_connection_retry_exposes_truthful_busy_state() -> None:
    section = SCRIPT[SCRIPT.index("function setServerConnectionState") : SCRIPT.index("async function retryServerConnection")]
    assert 'retry.setAttribute("aria-busy",String(state==="checking"))' in section
    assert 'retry.textContent=state==="checking"?"Checking...":"Retry Connection"' in section
    assert 'retry.disabled=state==="checking"' in section


def test_mobile_connection_recovery_stays_above_fixed_operator_controls() -> None:
    assert 'body.studiox-ui4[data-ui4-workspace="live"] .server-connection-banner' in CSS
    assert 'bottom:calc(132px + env(safe-area-inset-bottom,0px))' in CSS
    assert 'bottom:calc(62px + env(safe-area-inset-bottom,0px))' in CSS
    assert "top:auto" in CSS
    assert "transform:none" in CSS
