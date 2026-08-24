from pathlib import Path


def test_studiox_uses_recognition_state_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (
        root
        / "rareiq"
        / "web"
        / "static"
        / "studiox.js"
    ).read_text(
        encoding="utf-8"
    )

    assert "result?.recognition_state" in script
    assert "/api/recognition-state?t=${Date.now()}" in script
    assert "snapshot.primary_candidate" in script
    assert "snapshot?.pipeline_stages" in script
    assert "window.__rareiqRecognitionPoll" in script
    assert "verifiedVisualCandidate" in script
    assert "realIdentityCandidate" in script
    assert "authoritativeSetLockedCandidate" in script
    assert "isAuthoritativeSetLockedCard" in script
    assert 'querySelectorAll("button[data-workspace-density]")' in script
    assert 'querySelectorAll("[data-workspace-density]")' not in script
    assert "const presentableCandidate" in script
    assert "candidate.verification_strong === true" in script
    assert "const isPresentableCandidate" in script
    assert 'candidate.retrieval_only === true' in script
    assert 'source === "ocr_provisional"' in script
    assert 'source === "global_visual_index" && !safeSetLockedProvisional' in script
    assert 'candidate.set_locked_identity_agreement === true' in script
    assert 'candidate.provisional === true' in script
    assert "identityAgrees(candidate) &&" in script
    assert script.index("verifiedVisualCandidate ||", script.index("let card =")) < script.index("realIdentityCandidate ||", script.index("let card ="))
    assert script.index("presentableProvisional ||", script.index("let card =")) < script.index("presentableCandidate ||", script.index("let card ="))
    assert '$("cardName").textContent="Verifying Card"' in script
    assert "databaseCandidate ||" not in script
    assert "snapshot?.overall_confidence ??\n      snapshot?.confidence" not in script
    assert "currentServerSessionId" in script
    assert "result?.server_session_id" in script
    assert 'resetRecognitionPresentation("backend_empty")' in script
    assert "newestRecognitionGeneration=-1" in script
    assert "newestRecognitionRevision=-1" in script
    assert 'hadPreviousSession ? "server_session_changed"' in script
    assert 'if(serverSessionId && serverSessionId!==currentServerSessionId)' in script


def test_server_exposes_process_stable_session_id_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    server = (root / "rareiq" / "web" / "server.py").read_text(
        encoding="utf-8"
    )
    assert "SERVER_SESSION_ID = uuid.uuid4().hex" in server
    assert server.count('"server_session_id": SERVER_SESSION_ID') >= 3


def test_empty_and_server_change_remove_previous_artwork_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "rareiq" / "web" / "static" / "studiox.js").read_text(
        encoding="utf-8"
    )
    reset_start = script.index("function resetRecognitionPresentation")
    reset_end = script.index("async function loadRecognition", reset_start)
    reset = script[reset_start:reset_end]
    assert '$("cardArt").innerHTML=""' in reset
    assert '$("cardName").textContent="Ready to Scan"' in reset
    assert '$("confidence").textContent="0%"' in reset
    assert '$("cardStatus").textContent="READY"' in reset
    assert 'renderPipeline([],false)' in reset


def test_control_html_busts_studiox_cache() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (
        root
        / "rareiq"
        / "web"
        / "static"
        / "control.html"
    ).read_text(
        encoding="utf-8"
    )

    version = html.split('data-studiox-build="', 1)[1].split('"', 1)[0]
    assert f"/static/studiox.js?v={version}" in html
    assert "/static/studiox.css?v=6.4.12" in html
    assert f"/static/studiox_ui4_tokens.css?v={version}" in html
    assert f"/static/studiox_update15.css?v={version}" in html
    assert html.index("studiox_ui4_tokens.css") < html.index("studiox_update15.css")
    assert html.index("studiox_update15.css") < html.index(f"studiox.js?v={version}")
    assert 'http-equiv="Cache-Control"' in html


def test_primary_card_actions_render_above_recognition_content() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "rareiq" / "web" / "static" / "control.html").read_text(
        encoding="utf-8"
    )
    script = (root / "rareiq" / "web" / "static" / "studiox.js").read_text(
        encoding="utf-8"
    )

    assert html.index('class="inspector-footer inspector-command-strip"') < html.index(
        'id="recognitionStatePanel"'
    )
    assert html.count('id="approveButton"') == 1
    assert html.count('id="rejectButton"') == 1
    assert html.count('id="nextClearButton"') == 1
    assert 'currentView.appendChild(stickyActions)' not in script
    stylesheet = (
        root / "rareiq" / "web" / "static" / "studiox_update15.css"
    ).read_text(encoding="utf-8")
    command_strip = stylesheet[stylesheet.rindex("body.studiox-ui4.studiox-premium .inspector-footer.inspector-command-strip{"):]
    assert "display:none!important" in command_strip
    assert "body.studiox-ui4.studiox-premium .result-decision-actions{" in command_strip
    assert "display:grid!important" in command_strip
    assert ".inspector-actions .riq-button:last-child{display:none}" not in stylesheet
    assert ".inspector-actions button:last-child{display:none}" not in stylesheet
    assert "order:99" not in stylesheet
    assert "grid-column:4" not in stylesheet
    assert (
        ".inspector-actions #approveButton{\n    grid-column:span 2"
        not in stylesheet
    )


def test_recognition_decisions_are_guarded_against_duplicate_submissions() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "rareiq" / "web" / "static" / "studiox.js").read_text(
        encoding="utf-8"
    )

    assert "let recognitionDecisionInFlight=false" in script
    assert "let recognitionClearInFlight=false" in script
    assert "button.disabled||recognitionMutationInFlight()" in script
    assert "recognitionDecisionInFlight=true" in script
    assert "recognitionDecisionInFlight=false" in script
    assert "recognitionClearInFlight=true" in script
    assert "recognitionClearInFlight=false" in script
    for button_id in (
        "approveButton",
        "rejectButton",
        "decisionApproveButton",
        "decisionRejectButton",
    ):
        assert f'"{button_id}"' in script


def test_optional_ui_observers_cannot_abort_tool_initialization() -> None:
    root = Path(__file__).resolve().parents[1]
    studio = (root / "rareiq" / "web" / "static" / "studiox.js").read_text(encoding="utf-8")
    assert "const observeStudioXTarget=" in studio
    assert 'target instanceof Node' in studio
    assert "try{observer.observe(target,options);return true}catch" in studio


def test_live_diagnostics_exposes_detected_identifier_evidence() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "rareiq" / "web" / "static" / "control.html").read_text(
        encoding="utf-8"
    )
    script = (root / "rareiq" / "web" / "static" / "studiox.js").read_text(
        encoding="utf-8"
    )

    assert 'id="diagnosticCollectorNumber"' in html
    assert 'id="diagnosticPrintedCode"' in html
    assert 'id="diagnosticCollectorConfidence"' in html
    assert 'id="diagnosticIdentifierVerification"' in html
    assert "snapshot.ocr_collector_number" in script
    assert "snapshot.ocr_printed_code" in script
    assert "snapshot.identifier_reference_match" in script
    diagnostics = script[
        script.index("function renderDiagnosticsWidget"):
        script.index("function renderAutoScreenshotWidget")
    ]
    assert "snapshot.collector_number||" not in diagnostics
    assert '"Reference confirmed"' in script


def test_operator_card_decisions_call_backend_and_use_authoritative_session() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "rareiq" / "web" / "static" / "studiox.js").read_text(
        encoding="utf-8"
    )

    assert 'url:recognitionDecisionUrl("/api/session/confirm-recognition")' in script
    assert 'url:recognitionDecisionUrl("/api/session/reject-recognition")' in script
    assert 'const stateId=String(window.__rareiqCardContext?.snapshot?.state_id||"")' in script
    assert 'const payload=await api(url,{method:"POST",body:"{}"})' in script
    assert "applyAuthoritativeSession(payload.session)" in script
    assert 'notify("Card Action Failed",detail,"error")' in script


def test_studiox_renders_camera_resolution_and_scan_zone() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (
        root / "rareiq" / "web" / "static" / "studiox.js"
    ).read_text(encoding="utf-8")
    stylesheet = (
        root / "rareiq" / "web" / "static" / "studiox.css"
    ).read_text(encoding="utf-8")

    assert "vision.actual_resolution" in script
    assert "vision.requested_resolution" in script
    assert "vision.resolution_fallback" in script
    assert "vision.scan_zone" in script
    assert "function alignScanZone" in script
    assert 'fit==="cover"' in script
    assert 'fit==="contain"' not in script
    assert ".riq-pill.fallback" in stylesheet


def test_studiox_requires_authoritative_fresh_camera_health() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "rareiq" / "web" / "static" / "studiox.js").read_text(
        encoding="utf-8"
    )
    assert 'manager.state==="running"' in script
    assert 'manager.worker_alive===true' in script
    assert 'manager.frame_fresh===true' in script
    assert 'vision.running===true' in script
    assert '"CAMERA STALLED"' in script
    assert 'result?.already_running' in script
    assert 'status?.running ||' not in script


def test_single_card_identify_widget_shows_temporal_progress() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "rareiq" / "web" / "static" / "studiox.js").read_text(
        encoding="utf-8"
    )
    assert '"Temporal confirmation"' in script
    assert "snapshot.temporal_confirmation===true" in script
    assert "`Confirming ${temporalProgress}/${temporalRequired}`" in script
    assert "stable scans" in script


def test_single_card_identify_widget_explains_exact_version_ambiguity() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "rareiq" / "web" / "static" / "studiox.js").read_text(
        encoding="utf-8"
    )
    assert 'snapshot.exact_reference_diagnostics' in script
    assert '"Exact-version decision"' in script
    assert '"Leading reference"' in script
    assert '"Runner-up reference"' in script
    assert '"Version confirmation"' in script
    assert 'distinct captures' in script
    assert '"Follow-up sample"' in script
    assert 'waiting-for-fresh-foil-sample' in script
    assert 'timed-out-safely' in script
    assert 'selected-card-lost' in script

