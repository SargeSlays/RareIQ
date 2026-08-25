from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def function_body(name: str, next_name: str) -> str:
    start = JS.index(f"function {name}")
    end = JS.index(f"function {next_name}", start)
    return JS[start:end]


def test_empty_and_replacement_states_never_preserve_a_stale_card() -> None:
    load = JS[JS.index("async function loadRecognition"):]
    assert "hadVisibleCard" not in load
    assert "missingCurrentCard" not in load
    assert "provisionalLooksUnidentified" not in load
    assert '["IDLE", "READY", "LOST"].includes(phase)' in load
    clear = load.index("if (clearInspector) {")
    reset = load.index('resetRecognitionPresentation("backend_empty")', clear)
    finish = load.index("return;", reset)
    assert clear < reset < finish


def test_operator_decision_strip_explains_the_next_truthful_action() -> None:
    assert HTML.count('id="decisionGuidance"') == 1
    assert 'role="status" aria-live="polite"' in HTML
    assert 'data-operator-state="waiting"' in HTML
    assert 'aria-describedby="decisionGuidance"' in HTML
    guidance = function_body(
        "deriveOperatorDecisionGuidance",
        "renderOperatorDecisionGuidance",
    )
    for state in (
        "verified",
        "catalog-required",
        "set-required",
        "review-required",
        "processing",
        "error",
        "waiting",
    ):
        assert f'state:"{state}"' in guidance
    assert "Approval requires a verified identity" in JS
    assert 'strip.dataset.operatorState=model.state' in JS


def test_reference_missing_can_search_catalog_from_current_validated_crop() -> None:
    candidates = function_body("renderCandidatesWidget", "renderDetailsWidget")
    correction = function_body(
        "openMatchCorrectionWorkflow",
        "approveReferenceSelection",
    )
    assert 'context.presentation.title==="REFERENCE MISSING"' in candidates
    assert "snapshot.state_id" in candidates
    assert "cardPresent" in candidates
    assert '"Search Catalog"' in candidates
    assert "truthfulLockedCapture(context)" in correction
    assert '`/api/camera/crop.jpg?generation=${generation}`' in correction
    assert 'requestAnimationFrame(()=>$("referenceCatalogSearchInput")?.focus())' in correction
    assert "operatorApprove()" not in correction


def test_decision_actions_remain_verification_gated_and_keyboard_accessible() -> None:
    mutation = function_body(
        "syncRecognitionMutationControls",
        "runRecognitionDecision",
    )
    assert 'actionable=window.__rareiqCardContext?.verified===true' in mutation
    assert 'connectionUnavailable=["offline","unreachable","checking"]' in mutation
    assert "busy||connectionUnavailable" in mutation
    assert 'id="decisionApproveButton"' in HTML
    assert 'id="decisionRejectButton"' in HTML
    assert 'aria-keyshortcuts="A"' in HTML
    assert 'aria-keyshortcuts="R"' in HTML
    assert ".result-decision-actions button:focus-visible" in CSS


def test_camera_disconnect_clears_identity_and_disables_live_decisions() -> None:
    disconnected = function_body(
        "setCameraDisconnectedPresentation",
        "readSelectedCamera",
    )
    assert 'resetRecognitionPresentation("camera_disconnected")' in disconnected
    assert "deriveSharedCardContext(" in disconnected
    assert 'null,\n    {phase:"ERROR",card_present:false' in disconnected
    assert 'camera_error:detail' in disconnected


def test_details_shortcut_opens_the_real_details_widget() -> None:
    details = function_body("operatorDetails", "isTypingTarget")
    assert 'setUI4InspectorView("current",false)' in details
    assert 'setStudioXWorkbenchTab("card")' in details
    assert 'id!=="details"' in details
    assert "applyStudioXWidgetLayout({persist:true})" in details
    assert 'data-studiox-widget="details"' in details
    assert "queued" not in details.lower()


def test_live_operator_cache_marker_and_unique_ids() -> None:
    assert HTML.count("shell=6.8.93-camera-workspace1") == 2
    ids = [fragment.split('"', 1)[0] for fragment in HTML.split('id="')[1:]]
    assert len(ids) == len(set(ids))
