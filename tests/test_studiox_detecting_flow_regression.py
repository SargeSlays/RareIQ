from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def js_section(start: str, end: str) -> str:
    begin = JS.index(start)
    return JS[begin:JS.index(end, begin)]


def test_detecting_uses_one_presentation_state_contract():
    render = js_section(
        "function renderLiveAnalysisTimeline",
        "function renderAuthoritativeCardContextHeader",
    )
    assert "currentView.dataset.presentationState=state" in render
    assert "inspectorMain.dataset.presentationState=state" in render
    assert 'const showCardContext=recognized||context.presentation.key==="set-mismatch"' in render
    assert "header.hidden=!showCardContext" in render
    assert "header.inert=!showCardContext" in render
    assert "document.body.dataset.presentationState=context.presentation.key" in JS


def test_full_identity_requires_truthful_recognized_identity():
    identity = js_section(
        "function hasTruthfulRecognizedIdentity",
        "function renderLiveAnalysisTimeline",
    )
    assert '["english_name","canonical_name","printed_name","name"]' in identity
    assert '["collector_number","official_collector_number","set_id","set_name"]' in identity
    assert '["candidate-found","review-needed","exact-match"]' in identity
    assert "context.verified||hasTruthfulRecognizedIdentity(context)" in JS


def test_detecting_workspace_is_normal_flow_without_overlapping_layers():
    assert ".ui4-current-card-view{\n  display:flex!important" in CSS
    assert "#inspectorMain{\n  position:relative" in CSS
    assert "display:flex!important" in CSS
    assert "grid-auto-rows:max-content" in CSS
    assert "position:relative;\n  align-self:start;\n  contain:layout paint" in CSS
    assert ".premium-card-context-header[hidden]" in CSS
    assert "display:none!important" in CSS
    assert '[data-presentation-state="detecting"]' in CSS


def test_prelock_dependency_copy_is_not_duplicated_by_full_identity():
    assert HTML.count("Waiting for confirmed identity") == 0
    assert JS.count('"identity-pending":"Waiting for confirmed identity"') == 1
    assert '$("cardValue").textContent="Waiting for confirmed identity"' in JS
    assert "header.hidden=!showCardContext" in JS


def test_footer_and_actions_have_stable_rows():
    assert "grid-template-rows:auto auto" in CSS
    assert ".inspector-actions{\n  position:relative" in CSS
    assert "grid-row:2" in CSS
    update = js_section(
        "function updateSharedCardContext",
        "function initializeStudioXUI4",
    )
    assert "button.disabled=!actionable" in update
    assert '$("nextClearButton").disabled=false' in update
    assert 'onclick="operatorApprove()"' in HTML
    assert 'onclick="operatorReject()"' in HTML


def test_geometry_gate_rejects_non_card_polygons_conservatively():
    quality = js_section(
        "function cardFocusGeometryQuality",
        "function clearCardFocusGeometry",
    )
    assert "cardFocusSegmentsIntersect" in quality
    assert "corner-order" in quality
    assert "aspect<.58||aspect>.84" in quality
    assert "boundsWidth>.56||boundsHeight>.9" in quality
    assert "area/scanArea>.56" in quality
    assert "implausible-aspect" in quality
    assert "implausible-bounds" in quality
    assert "implausible-area" in quality
    assert "Card focus unavailable — unstable card geometry" in JS


def test_last_valid_geometry_is_retained_briefly_then_cleared():
    smoothing = js_section(
        "function smoothedCardFocusGeometry",
        "function applySecondaryCardFocusGeometry",
    )
    assert "CARD_FOCUS_LAST_VALID_MS = 1800" in JS
    assert "lastValidCardFocusGeometry" in smoothing
    assert "Date.now()-lastValidCardFocusAt<=CARD_FOCUS_LAST_VALID_MS" in smoothing
    reset = js_section(
        "function resetRecognitionPresentation",
        "function normalizeStudioXPreferences",
    )
    assert "clearCardFocusGeometry()" in reset
    active_change = js_section("async function selectCamera", "async function startSelectedCamera")
    assert 'resetRecognitionPresentation("active_source_changed")' in active_change


def test_no_duplicate_ids_and_cache_advanced():
    ids = [part.split('"', 1)[0] for part in HTML.split('id="')[1:]]
    assert len(ids) == len(set(ids))
    version = HTML.split('data-studiox-build="', 1)[1].split('"', 1)[0]
    assert f"/static/studiox.js?v={version}" in HTML
