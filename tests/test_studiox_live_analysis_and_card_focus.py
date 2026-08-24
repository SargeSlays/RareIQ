from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
TOKENS = (ROOT / "rareiq/web/static/studiox_ui4_tokens.css").read_text(encoding="utf-8")


def function_body(name: str, next_name: str) -> str:
    start = JS.index(f"function {name}")
    end = JS.index(f"function {next_name}", start)
    return JS[start:end]


def test_authoritative_presentation_drives_every_visible_state_surface():
    update = function_body("updateSharedCardContext", "initializeStudioXUI4")
    assert "applyRecognitionPresentation(context.presentation)" in update
    assert "renderAuthoritativeCardContextHeader(context)" in update
    assert "renderLiveAnalysisTimeline(context)" in JS
    assert '$("cardStatus").textContent=presentation.title' in JS
    assert '$("cameraFeedStateLabel").textContent=title' in JS
    assert '$("cardName").textContent=' in JS
    assert "presentation.placeholderTitle" in JS
    assert 'key==="verifying"' in JS
    assert 'title:"VERIFYING"' in JS
    assert 'placeholderTitle:"Verifying Card"' in JS


def test_all_explicit_recognition_states_are_supported():
    for state in (
        "ready",
        "detecting",
        "scanning",
        "candidate-found",
        "verifying",
        "exact-match",
        "review-needed",
        "error",
    ):
        assert state in JS
    assert "SEARCHING + VERIFYING" not in HTML
    assert "Ready to Scan" not in JS[JS.index("function renderAuthoritativeCardContextHeader"):]


def test_live_timeline_is_truthful_and_locked_identity_replaces_it():
    for step in ("detection", "geometry", "artwork", "collector", "catalog"):
        assert HTML.count(f'data-analysis-step="{step}"') == 1
    assert 'const scanning=!recognized&&!["ready","exact-match"]' in JS
    assert "timeline.hidden=!scanning" in JS
    assert 'const showCardContext=recognized||context.presentation.key==="set-mismatch"' in JS
    assert "header.hidden=!showCardContext" in JS
    assert 'reference_image_url:`/api/camera/crop.jpg?generation=${generation}`' in JS
    assert 'authoritativeVerificationState==="SET_MISMATCH"' in JS
    assert "deriveLiveAnalysisSteps(context)" in JS
    assert "context.verified?\"complete\"" in JS


def test_scanning_widgets_wait_for_truthful_dependencies():
    assert "Catalog verification in progress" in JS
    assert "Waiting for stronger evidence" in JS
    assert "waiting-for-stable-capture" in JS
    assert '"identity-pending":"Waiting for confirmed identity"' in JS
    assert "Searching catalog candidates" in JS
    assert 'widget.dataset.widgetSize="compact"' in JS
    assert "Estimated AI condition analysis" in HTML


def test_card_focus_uses_detected_geometry_not_unconditional_scan_zone():
    geometry = function_body("normalizedCardFocusGeometry", "smoothedCardFocusGeometry")
    assert "vision?.card_corners" in geometry
    assert "vision?.perspective_corners" in geometry
    assert "vision?.polygon" in geometry
    assert "vision?.stable===true" in geometry
    assert "vision?.scan_zone||null" not in geometry
    assert "if(!zone) return null" in geometry
    assert 'image.dataset.focusPresentation="tight-card-crop"' in JS
    assert "image.style.clipPath=`polygon(${polygon})`" in JS
    assert "point.x>=-.08&&point.x<=1.08" in JS
    assert "Math.min(8" in JS
    assert "smoothedCardFocusGeometry" in JS


def test_card_focus_fallback_freeze_and_media_truthfulness():
    card_focus = JS[JS.index('}else if(mode==="card-focus")'):JS.index('}else if(mode==="locked-capture")')]
    assert "Card focus unavailable" in card_focus
    assert "truthfulLockedCapture(context)" in card_focus
    assert 'lockedCapture?.url||"/api/camera/stream?viewer=secondary-card-focus"' in card_focus
    assert "reference_image_url" not in card_focus
    assert 'image.dataset.frameState=lockedCapture?"locked-capture":"live-active-source"' in card_focus


def test_card_focus_sizes_and_hidden_space_contract():
    assert "--secondary-bay-compact:clamp(150px,18vh,280px)" in TOKENS
    assert "--secondary-bay-standard:clamp(230px,29vh,620px)" in TOKENS
    assert "--secondary-bay-large:clamp(320px,39vh,820px)" in TOKENS
    assert '.studiox-secondary-bay[hidden]{display:none}' in CSS
    assert ".camera-workspace.has-secondary-bay .camera-stage-inner" in CSS
    assert 'data-bay-size="large"' in CSS


def test_next_clear_still_clears_stale_identity_and_media():
    reset = function_body("resetRecognitionPresentation", "normalizeStudioXPreferences")
    assert '$("cardArt").innerHTML=""' in reset
    assert "resetExtendedCardData()" in reset
    assert "previousCardId=null" in reset
    assert 'deriveRecognitionPresentation({phase:"IDLE"},null,[])' in reset
    assert 'requestNextRecognition().catch(error=>' in JS


def test_accessibility_motion_and_unique_ids_contract():
    assert 'id="liveAnalysisTimeline"' in HTML
    assert 'aria-label="Live recognition analysis"' in HTML
    assert "@media(prefers-reduced-motion:reduce)" in CSS
    ids = []
    for fragment in HTML.split('id="')[1:]:
        ids.append(fragment.split('"', 1)[0])
    assert len(ids) == len(set(ids))
