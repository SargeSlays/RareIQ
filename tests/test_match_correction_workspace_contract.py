from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_verified_match_exposes_direct_correction_entry_points():
    assert 'id="correctMatchButton"' in HTML
    assert 'id="candidateReviewButton"' in HTML
    assert "function openMatchCorrectionWorkflow()" in JS
    assert 'correctButton.hidden=!correctionAvailable' in JS
    assert 'correctButton.textContent=context.verified?"Correct Match":"Review Match"' in JS
    assert 'reviewButton.textContent=context.verified?"Correct Match":"Review Candidates"' in JS


def test_correction_workflow_opens_alternatives_and_uses_learning_endpoint():
    workflow = JS[
        JS.index("function openMatchCorrectionWorkflow"):
        JS.index("function renderUI4RecentScanDetail")
    ]
    assert '$("referenceCandidates").hidden=false' in workflow
    assert "renderReferenceCandidates()" in workflow
    assert '"/api/session/confirm-recognition-candidate"' in JS
    assert 'notify("Corrected Match Approved"' in JS


def test_correction_workflow_can_search_and_confirm_full_local_catalog():
    assert 'id="referenceCatalogSearchForm"' in HTML
    assert 'id="referenceCatalogSearchInput"' in HTML
    assert "/api/intelligence/catalog-search?q=" in JS
    assert '"/api/session/confirm-recognition-catalog-candidate"' in JS
    assert "referenceSelectedCatalogCandidate" in JS


def test_review_needed_opens_the_real_candidate_comparison_workflow():
    assert 'onclick="openMatchCorrectionWorkflow()">Review identity</button>' in HTML
    action = JS.split("function runStudioXWorkbenchAction", 1)[1].split(
        "function openLiveSargeAdvisor", 1
    )[0]
    assert "openMatchCorrectionWorkflow()" in action
    assert "setUI4DiagnosticsOpen(true)" not in action


def test_review_can_start_from_candidate_reference_when_card_hero_is_hidden():
    workflow = JS.split("function openMatchCorrectionWorkflow", 1)[1].split(
        "async function approveReferenceSelection", 1
    )[0]
    assert "candidates.find(candidate=>multiCardReferenceImage(candidate))" in workflow
    assert "multiCardReferenceImage(initial)" in workflow
    assert "openReferenceLightbox(source,title,meta)" in workflow


def test_explicit_candidate_selection_unlocks_only_the_review_approval():
    verification = JS.split("function syncReferenceVerification", 1)[1].split(
        "function selectReferenceCorrectionCandidate", 1
    )[0]
    assert "const explicitSelection=Boolean(selected)" in verification
    assert "(!explicitSelection&&Boolean($(\"approveButton\")?.disabled))" in verification
    selection = JS.split("function selectReferenceCorrectionCandidate", 1)[1].split(
        "function makeReferenceCandidateButton", 1
    )[0]
    assert "syncReferenceVerification()" in selection


def test_review_dialog_explains_conflicts_and_uses_one_shot_mutation_guard():
    assert 'id="referenceIdentityConflict" role="status" hidden' in HTML
    assert "function syncReferenceIdentityConflict" in JS
    approval = JS.split("async function approveReferenceSelection", 1)[1].split(
        "async function rejectReferenceSelection", 1
    )[0]
    assert "if(recognitionMutationInFlight())return null" in approval
    assert "recognitionDecisionInFlight=true" in approval
    assert "recognitionDecisionInFlight=false" in approval
    rejection = JS.split("async function rejectReferenceSelection", 1)[1].split(
        "function renderUI4RecentScanDetail", 1
    )[0]
    assert '"/api/session/reject-recognition?state_id="' not in rejection
    assert "/api/session/reject-recognition?state_id=${encodeURIComponent(stateId)}" in rejection


def test_candidate_review_recommends_only_complete_observed_evidence_matches():
    evidence = JS.split("function referenceCandidateEvidence", 1)[1].split(
        "function syncReferenceIdentityConflict", 1
    )[0]
    assert 'compare("collector number"' in evidence
    assert 'compare("language"' in evidence
    assert 'recommended=checks.length>0&&agreements.length===checks.length' in evidence
    assert 'state:recommended?"recommended"' in evidence
    assert 'label:recommended?"EVIDENCE MATCH"' in evidence


def test_evidence_recommendation_never_selects_or_approves_a_candidate():
    evidence = JS.split("function referenceCandidateEvidence", 1)[1].split(
        "function syncReferenceIdentityConflict", 1
    )[0]
    assert "referenceSelectedCandidate=" not in evidence
    assert "referenceSelectedCatalogCandidate=" not in evidence
    assert "approveReferenceSelection" not in evidence
    assert "/api/session/" not in evidence


def test_candidate_buttons_expose_truthful_evidence_states():
    button = JS.split("function makeReferenceCandidateButton", 1)[1].split(
        "function renderReferenceCandidates", 1
    )[0]
    assert "referenceCandidateEvidence(candidate)" in button
    assert "button.dataset.identityEvidence=evidence.state" in button
    assert "escapeHtml(evidence.label)" in button
    assert 'data-identity-evidence="recommended"' in CSS


def test_correction_history_exposes_recorded_identity_provenance():
    provenance = JS.split("function referenceCorrectionProvenance", 1)[1].split(
        "async function revokeReferenceCorrection", 1
    )[0]
    assert "resolution.observed_identity" in provenance
    assert "resolution.previous_catalog_identity" in provenance
    assert "resolution.selected_identity||row.candidate" in provenance
    assert '"Legacy correction · original review evidence was not recorded"' in provenance
    history = JS.split("async function loadReferenceCorrectionHistory", 1)[1].split(
        "function openReferenceLightbox", 1
    )[0]
    assert "escapeHtml(referenceCorrectionProvenance(row))" in history
    assert 'class="reference-correction-provenance"' in history


def test_correction_revocation_is_one_shot_and_reports_failure_truthfully():
    revoke = JS.split("async function revokeReferenceCorrection", 1)[1].split(
        "async function loadReferenceCorrectionHistory", 1
    )[0]
    assert "button?.disabled" in revoke
    assert 'button.textContent="Revoking…"' in revoke
    assert "result?.revoked!==true" in revoke
    assert 'notify("Correction Not Reverted"' in revoke
    assert "await loadReferenceCorrectionHistory()" in revoke
