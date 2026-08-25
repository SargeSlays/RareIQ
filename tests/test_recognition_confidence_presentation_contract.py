from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")


def test_signal_ring_has_a_dynamic_truthful_label():
    assert 'id="confidenceRingLabel">FUSION</span>' in HTML
    updater = JS.split("function updateConfidenceRing", 1)[1].split(
        "const STUDIOX_MODAL_FOCUSABLE", 1
    )[0]
    assert 'label="FUSION"' in updater
    assert "ring.dataset.confidenceKind" in updater
    assert 'identity verdict ${verdict}' in updater
    assert '$("confidenceRingLabel").textContent=normalizedLabel' in updater


def test_review_needed_uses_fusion_confidence_not_a_fake_match_percentage():
    presentation = JS.split("function applyRecognitionPresentation", 1)[1].split(
        "function setRecognitionState", 1
    )[0]
    assert 'key==="exact-match"?"MATCH":"FUSION"' in presentation
    assert "confidence," in presentation
    review = JS.split("function deriveRecognitionPresentation", 1)[1].split(
        "function stabilizeRecognitionPresentation", 1
    )[0]
    assert 'key:"review-needed"' in review
    assert "confidence" in review


def test_review_copy_skips_empty_conflicts_and_reports_real_evidence():
    formatter = JS.split(
        "function identityConflictPresentationDetail", 1
    )[1].split("function deriveRecognitionPresentation", 1)[0]
    assert "Boolean(observed&&catalog)" in formatter
    assert 'comparisons.slice(0,2)' in formatter
    assert "Observed ${label} ${observed}" in formatter
    assert "conflicts with catalog value ${catalog}" in formatter
    assert "Identity review required:" in formatter
    assert "Observed identity evidence conflicts with the catalog candidate." in formatter

    review = JS.split("function deriveRecognitionPresentation", 1)[1].split(
        "function stabilizeRecognitionPresentation", 1
    )[0]
    assert "identityConflictPresentationDetail(snapshot,card)" in review


def test_reference_missing_copy_uses_observed_catalog_query() -> None:
    formatter = JS.split(
        "function catalogGapPresentationDetail", 1
    )[1].split("function deriveRecognitionPresentation", 1)[0]
    assert "snapshot?.catalog_gap?.query" in formatter
    assert "No local reference matches observed" in formatter
    assert "Search or import the correct catalog record." in formatter

    presentation = JS.split(
        "function deriveRecognitionPresentation", 1
    )[1].split("function stabilizeRecognitionPresentation", 1)[0]
    assert 'title:"REFERENCE MISSING"' in presentation
    assert 'key:"review-needed"' in presentation


def test_only_authoritative_verification_promotes_the_ring_to_match():
    shared = JS.split("function updateSharedCardContext", 1)[1].split(
        "function applyStudioXExactMatchMoment", 1
    )[0]
    assert "if(context.verified===true)" in shared
    assert '),"MATCH","EXACT MATCH")' in shared
    assert 'key==="exact-match"?"MATCH":"FUSION"' in JS


def test_reset_states_restore_fusion_not_match_language():
    reset = JS.split("function resetRecognitionPresentation", 1)[1].split(
        "function isAuthoritativeSetLockedCard", 1
    )[0]
    assert 'updateConfidenceRing(0,"FUSION","READY")' in reset
