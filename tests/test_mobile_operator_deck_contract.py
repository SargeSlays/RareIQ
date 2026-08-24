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
        "mobileOperatorWakeLock",
        "mobileOperatorCapture",
        "mobileOperatorApprove",
        "mobileOperatorReject",
        "mobileOperatorHistoryLive",
        "mobileOperatorHistoryRefresh",
        "mobileOperatorNext",
        "mobileOperatorReconnect",
        "mobileOperatorStatus",
        "mobileOperatorViewCamera",
        "mobileOperatorViewBoth",
        "mobileOperatorViewCard",
        "mobileOperatorViewScans",
    ):
        assert HTML.count(f'id="{element_id}"') == 1
    assert 'aria-label="Mobile operator controls"' in HTML
    assert 'aria-label="Recognition actions"' in HTML
    assert 'aria-live="polite"' in HTML


def test_mobile_operator_actions_delegate_to_existing_paths_without_polling():
    initializer = JS[JS.index("function initializeStudioXUI4()") : JS.index("initializeStudioXUI4();")]
    assert '$("mobileOperatorCapture")?.addEventListener("click",()=>Promise.resolve().then(()=>captureRecognitionMode())' in initializer
    assert '$("mobileOperatorApprove")?.addEventListener("click",()=>$("approveButton")?.click())' in initializer
    assert '$("mobileOperatorReject")?.addEventListener("click",()=>$("rejectButton")?.click())' in initializer
    assert '$("mobileOperatorHistoryLive")?.addEventListener("click",()=>setMobileOperatorDestination("card"))' in initializer
    assert '$("mobileOperatorHistoryRefresh")?.addEventListener("click",loadUI4RecentScans)' in initializer
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


def test_mobile_deck_switches_to_existing_decision_actions_only_for_a_card():
    sync = JS[JS.index("function syncMobileOperatorDeck()") : JS.index("function setMobileOperatorView")]
    assert 'name!=="Waiting for card"' in sync
    assert '!$("approveButton")?.disabled||!$("rejectButton")?.disabled' in sync
    assert 'const actions=ui4InspectorView==="recent"?"history":decisionAvailable?"decision":"scan"' in sync
    assert "region.dataset.actions=actions" in sync
    assert '$("mobileOperatorApprove").disabled=connectionUnavailable||Boolean($("approveButton")?.disabled)' in sync
    assert '$("mobileOperatorReject").disabled=connectionUnavailable||Boolean($("rejectButton")?.disabled)' in sync
    assert '[data-mobile-decision-action]{display:none!important}' in CSS
    assert '[data-actions="decision"] .mobile-operator-actions>[data-mobile-scan-action]{display:none!important}' in CSS
    assert '[data-actions="decision"] .mobile-operator-actions>[data-mobile-decision-action]{display:grid!important}' in CSS


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


def test_mobile_workspace_switch_is_explicit_persistent_and_poll_free():
    section = JS[JS.index("function setMobileOperatorView") : JS.index("function syncResultDecisionStrip")]
    assert '["camera","both","card"].includes(requested)' in section
    assert 'document.body.dataset.mobileOperatorView=view' in section
    assert 'localStorage.setItem(MOBILE_OPERATOR_VIEW_KEY,view)' in section
    assert "setInterval" not in section
    assert "fetch(" not in section
    assert 'id="mobileOperatorViewBoth" data-mobile-operator-view="both" aria-pressed="true"' in HTML


def test_mobile_scans_delegates_to_existing_history_without_another_poll_loop():
    section = JS[JS.index("function setMobileOperatorDestination") : JS.index("function syncResultDecisionStrip")]
    assert 'setUI4InspectorView("recent")' in section
    assert 'setUI4InspectorView("current",false)' in section
    assert "setInterval" not in section
    assert "fetch(" not in section
    assert JS.count('/api/recent-pulls?limit=20') == 1


def test_history_mode_hides_live_mutations_and_offers_explicit_return_and_refresh():
    sync = JS[JS.index("function syncMobileOperatorDeck()") : JS.index("function setMobileOperatorView")]
    assert 'ui4InspectorView==="recent"?"history"' in sync
    inspector = JS[JS.index("function setUI4InspectorView") : JS.index("function syncInspectorNavigationState")]
    assert "syncMobileOperatorDeck();" in inspector
    assert '[data-actions="history"] .mobile-operator-actions>:not([data-mobile-history-action]):not(#mobileOperatorStatus){display:none!important}' in CSS
    assert '[data-actions="history"] .mobile-operator-actions>[data-mobile-history-action]{display:grid!important}' in CSS
    assert "setInterval(loadUI4RecentScans" not in JS
