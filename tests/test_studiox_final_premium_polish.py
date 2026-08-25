from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def section(start: str, end: str) -> str:
    return JS[JS.index(start):JS.index(end, JS.index(start))]


def test_prelock_identity_is_compact_and_not_duplicate_verification_copy():
    assert HTML.count('id="identityPendingPlaceholder"') == 1
    assert "IDENTITY PENDING" in HTML
    assert "Waiting for catalog confirmation" in HTML
    render = section(
        "function renderLiveAnalysisTimeline",
        "function renderAuthoritativeCardContextHeader",
    )
    assert "pending.hidden=showCardContext" in render
    assert "header.hidden=!showCardContext" in render
    assert "presentation.placeholderTitle" not in HTML


def test_market_never_claims_pricing_before_confirmed_identity():
    header = section(
        "function renderAuthoritativeCardContextHeader",
        "function renderIdentifyWidget",
    )
    market = section("function renderMarketWidget", "function renderCandidatesWidget")
    assert '$("cardValue").textContent="Waiting for confirmed identity"' in header
    assert '"identity-pending":"Waiting for confirmed identity"' in market
    assert 'pending:"Retrieving market intelligence"' in market
    assert '"no-data":"No verified market data is available for this card."' in market
    assert 'const state=context.card&&context.verified?context.market.key:"identity-pending"' in market


def test_timeline_completion_requires_payload_evidence():
    timeline = section("function deriveLiveAnalysisSteps", "function renderLiveAnalysisTimeline")
    assert "snapshot.card_present===true" in timeline
    assert "vision.stable===true" in timeline
    assert "context.card?.visual_score" in timeline
    assert "snapshot.collector_number" in timeline
    assert 'context.verified?"complete"' in timeline
    for label in (
        "Card detected",
        "Geometry stabilized",
        "Artwork analysis",
        "Collector number",
        "Catalog verification",
    ):
        assert label in HTML


def test_widget_defaults_only_affect_new_or_reset_layouts():
    defaults = section("const STUDIOX_DEFAULT_WIDGET_LAYOUT", "let studioXWidgetLayout")
    normalize = section("function normalizeStudioXWidgetLayout", "function loadStudioXWidgetLayout")
    assert 'collapsed:["details","diagnostics"]' in defaults
    assert 'identify:"wide"' in defaults
    assert 'candidates:"compact"' in defaults
    assert "value.sizes[id]" in normalize
    assert "hidden:validList(value.hidden)" in normalize
    assert "collapsed:validList(value.collapsed)" in normalize
    assert "pinned:validList(value.pinned)" in normalize
    assert "studioXWidgetLayout=defaultStudioXWidgetLayout()" in JS


def test_grade_market_and_candidates_hide_fake_content():
    grade = section("function renderAIGradeWidget", "function renderMarketWidget")
    market = section("function renderMarketWidget", "function renderCandidatesWidget")
    candidates = section("function renderCandidatesWidget", "function renderDetailsWidget")
    assert "gradeMetrics.hidden=!Object.values(values).some" in grade
    assert "AI Grade is unavailable because no grading provider is connected." in grade
    assert "node.hidden=!hasMetrics" in market
    assert "Searching catalog candidates" in candidates
    assert "Exact identity verified. No alternative candidates require review." in candidates
    assert "reviewButton.hidden=!correctionAvailable" in candidates
    assert "correctButton.hidden=!correctionAvailable" in candidates
    assert 'const reviewLabel=catalogGapSearchAvailable' in candidates
    assert 'correctButton.textContent=reviewLabel' in candidates
    assert '"Search Catalog"' in candidates


def test_auto_card_focus_respects_manual_hidden_and_is_stable():
    auto = section(
        "function deriveAutoSecondaryBayPresentation",
        "function loadSecondaryBayPreferences",
    )
    assert 'secondaryBayPreferences.mode==="hidden"' in auto
    assert "secondaryBayPreferences.manualPinned" in auto
    assert 'key==="verifying"&&geometry' in auto
    assert 'key==="exact-match"&&geometry' in auto
    assert '["detecting","scanning","candidate-found"].includes(key)&&geometry' in auto
    assert "secondaryBayPreferences=" not in auto
    assert 'manualPinned:mode!=="hidden"' in JS


def test_actions_are_hierarchical_and_safely_muted():
    assert HTML.index('id="approveButton"') < HTML.index('id="rejectButton"')
    assert HTML.count('id="nextClearButton"') == 1
    update = section("function updateSharedCardContext", "function initializeStudioXUI4")
    assert '["approveButton","rejectButton","detailsButton"]' in update
    assert "button.disabled=!actionable" in update
    assert '$("nextClearButton").disabled=recognitionMutationInFlight()' in update
    assert 'onclick="operatorApprove()"' in HTML
    assert 'onclick="operatorReject()"' in HTML


def test_final_polish_keeps_accessibility_and_motion_contracts():
    assert HTML.count('id="candidateReviewButton"') == 1
    assert "@media(prefers-reduced-motion:reduce)" in CSS
    ids = [fragment.split('"', 1)[0] for fragment in HTML.split('id="')[1:]]
    assert len(ids) == len(set(ids))
