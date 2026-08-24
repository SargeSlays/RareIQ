from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")


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
