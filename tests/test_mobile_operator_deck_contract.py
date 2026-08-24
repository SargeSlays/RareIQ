from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_mobile_operator_deck_has_unique_accessible_controls():
    for element_id in (
        "mobileOperatorState",
        "mobileOperatorCardName",
        "mobileOperatorConfidence",
        "mobileOperatorConnection",
        "mobileOperatorCapture",
        "mobileOperatorNext",
        "mobileOperatorReconnect",
        "mobileOperatorStatus",
    ):
        assert HTML.count(f'id="{element_id}"') == 1
    assert 'aria-label="Mobile operator controls"' in HTML
    assert 'aria-label="Recognition actions"' in HTML
    assert 'aria-live="polite"' in HTML


def test_mobile_operator_actions_delegate_to_existing_paths_without_polling():
    initializer = JS[JS.index("function initializeStudioXUI4()") : JS.index("initializeStudioXUI4();")]
    assert '$("mobileOperatorCapture")?.addEventListener("click",()=>Promise.resolve().then(()=>captureRecognitionMode())' in initializer
    assert '$("mobileOperatorNext")?.addEventListener("click",()=>$("nextClearButton")?.click())' in initializer
    assert '$("mobileOperatorReconnect")?.addEventListener("click",()=>Promise.resolve().then(()=>reconnectCamera())' in initializer
    assert '$("mobileOperatorStatus")?.addEventListener("click",()=>setUI4HealthOpen(!ui4HealthOpen))' in initializer
    assert "setInterval" not in initializer[initializer.index('$("mobileOperatorCapture")') : initializer.index("const observeStudioXTarget")]
    assert "fetch(" not in initializer[initializer.index('$("mobileOperatorCapture")') : initializer.index("const observeStudioXTarget")]


def test_mobile_summary_reuses_authoritative_recognition_sources():
    sync = JS[JS.index("function syncMobileOperatorDeck()") : JS.index("function syncResultDecisionStrip()")]
    for source_id in ("cardName", "confidenceRingValue", "identityVerdictBadge", "recognitionStateLabel", "nextClearButton"):
        assert f'$("{source_id}")' in sync
    assert "syncMobileOperatorDeck();" in JS


def test_mobile_deck_reuses_connection_events_and_blocks_unsafe_actions():
    sync = JS[JS.index("function syncMobileOperatorDeck()") : JS.index("function syncResultDecisionStrip()")]
    connection = JS[JS.index("function setServerConnectionState") : JS.index("async function retryServerConnection")]
    assert '["offline","unreachable","checking"].includes(serverConnectionState)' in sync
    assert 'region.dataset.connection=serverConnectionState' in sync
    assert 'setCardText("mobileOperatorConnection",connectionLabel)' in sync
    for action_id in ("mobileOperatorCapture", "mobileOperatorNext", "mobileOperatorReconnect"):
        assert f'$("{action_id}").disabled=connectionUnavailable' in sync
    assert "syncMobileOperatorDeck();" in connection
    assert "setInterval" not in connection


def test_mobile_deck_is_touch_sized_and_does_not_change_desktop_geometry():
    mobile_css = CSS[CSS.index("/* Update 6.8.9 — mobile operator shell foundation.") :]
    assert "@media(max-width:959px)" in mobile_css
    assert ".ui4-mobile-action-region" in mobile_css
    assert "min-height:46px!important" in mobile_css
    assert "bottom:calc(70px + env(safe-area-inset-bottom,0px))!important" in mobile_css
    assert "grid-template-columns:repeat(4,minmax(44px,1fr))!important" in mobile_css
