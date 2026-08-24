import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "rareiq" / "web" / "static"
HTML = (STATIC / "control.html").read_text(encoding="utf-8")
JS = (STATIC / "studiox.js").read_text(encoding="utf-8")
CSS = (STATIC / "studiox_update15.css").read_text(encoding="utf-8")
TOKENS = (STATIC / "studiox_ui4_tokens.css").read_text(encoding="utf-8")


def test_premium_type_and_material_tokens_exist() -> None:
    for token in (
        "--premium-title-size",
        "--premium-widget-title-size",
        "--premium-label-size",
        "--premium-metric-font",
        "--premium-surface-highlight",
        "--premium-orb-cyan",
    ):
        assert token in TOKENS
    assert "font-variant-numeric:tabular-nums" in CSS
    assert "Premium visual finishing pass" in CSS


def test_identity_hero_and_verdict_badges_keep_truthful_ids() -> None:
    for element_id in (
        "cardContextHeader",
        "cardArt",
        "cardName",
        "cardEnglishName",
        "cardMeta",
        "cardValue",
        "identityVerdictBadge",
    ):
        assert HTML.count(f'id="{element_id}"') == 1
    assert ".premium-card-context-header" in CSS
    assert '.identity-verdict-badge[data-verdict="exact-match"]' in CSS
    assert 'badge.textContent=verified' in JS
    assert '?"REVIEW NEEDED"' in JS
    assert ':"CANDIDATE · VERIFYING"' in JS


def test_widget_hierarchy_is_visual_only() -> None:
    assert '[data-studiox-widget="identify"]' in CSS
    assert '[data-studiox-widget="ai-grade"]' in CSS
    assert '[data-studiox-widget="market"]' in CSS
    assert '[data-studiox-widget="candidates"]' in CSS
    assert '[data-studiox-widget="auto-screenshot"]' in CSS
    assert "STUDIOX_WIDGET_RENDERERS" in JS


def test_exact_match_moment_is_one_shot_per_stable_context() -> None:
    start = JS.index("function applyStudioXExactMatchMoment")
    end = JS.index("function initializeStudioXUI4", start)
    hook = JS[start:end]
    assert "context?.snapshot?.generation" in hook
    assert "context?.identityKey" in hook
    assert "if(key===studioXExactMatchMomentKey) return" in hook
    assert 'classList.add("studiox-exact-match-moment")' in hook
    assert "setTimeout" in hook
    assert "studioxExactMatchResolve" in CSS


def test_motion_is_restrained_and_accessible() -> None:
    assert "@media(prefers-reduced-motion:reduce)" in CSS
    assert "animation-duration:.01ms!important" in CSS
    assert "transition-duration:.01ms!important" in CSS
    assert "confetti" not in CSS.lower()


def test_camera_and_command_bar_contracts_are_unchanged() -> None:
    assert "object-fit:contain" in CSS
    for marker in (
        "premium-source-control",
        "studiox-layout-control",
        "premium-view-control",
        "premium-actions-control",
    ):
        assert HTML.count(marker) == 1
    version = re.search(r'data-studiox-build="([^"]+)"', HTML).group(1)
    assert f"/static/studiox.js?v={version}" in HTML


def test_shell_containment_and_capture_alignment_contracts() -> None:
    assert "--sx-shell-sidebar-width:148px" in TOKENS
    assert ".ui4-navigation-rail .nav-button" in CSS
    assert "width:calc(100% - (2 * var(--sx-shell-gutter)))" in CSS
    assert ".premium-capture-action{position:relative;z-index:auto" in CSS
    assert "Shell containment and permanent Camera 2 staging bay" in CSS


def test_spacing_scale_and_vertical_rhythm_contracts() -> None:
    for token in (
        "--sx-space-1:4px",
        "--sx-space-2:8px",
        "--sx-space-3:12px",
        "--sx-space-4:16px",
        "--sx-space-5:20px",
        "--sx-space-6:24px",
        "--sx-space-7:32px",
        "--sx-panel-padding",
        "--sx-widget-gap",
        "--sx-column-gap",
    ):
        assert token in TOKENS
    assert "Studio X spacing, alignment, and vertical-rhythm correction" in CSS
    assert "min-height:36px" in CSS
    assert "min-height:40px" in CSS
    assert "grid-template-columns:minmax(128px,.7fr) minmax(0,1fr)" in CSS


def test_native_4k_density_contracts_and_empty_metadata_filter() -> None:
    assert "Native-4K composition and information-density repair" in CSS
    assert "--sx-density-hero-max:420px" in TOKENS
    assert "--sx-density-identify-max:286px" in TOKENS
    assert "aspect-ratio:16/9" in CSS
    assert "function syncCardMetadataVisibility" in JS
    assert 'field.hidden=!text||text==="--"' in JS
    assert "syncCardMetadataVisibility();" in JS
    assert ".ui4-identity-grid>div[hidden]{display:none}" in CSS


def test_final_native_4k_workspace_proportions_protect_intelligence_width() -> None:
    assert "Final native-4K proportion and Camera 2 presentation repair" in CSS
    assert "grid-template-columns:148px minmax(0,55fr) minmax(800px,45fr)!important" in CSS
    assert "grid-template-columns:repeat(2,minmax(360px,1fr))" in CSS
    assert "grid-template-columns:repeat(2,minmax(280px,1fr))" in CSS
    assert "white-space:nowrap" in CSS
    assert "width:min(560px,calc(100% - 32px))" in CSS
    assert "grid-template-columns:minmax(0,1fr)" in CSS


def test_final_micro_polish_preserves_accessible_focus_and_widget_readability() -> None:
    assert "Final Studio X micro-polish" in CSS
    assert '[data-studiox-widget="identify"] .studiox-widget-focus:focus-visible' in CSS
    assert "box-shadow:0 2px 0 rgba(98,214,255,.45)!important" in CSS
    assert "font-size:12.5px" in CSS
    assert "margin-top:4px" in CSS


def test_viewer_inspection_header_uses_truthful_existing_state() -> None:
    for element_id in (
        "viewerInspectionHeader",
        "viewerInspectionMode",
        "viewerInspectionCardState",
        "viewerInspectionRecognitionMode",
    ):
        assert HTML.count(f'id="{element_id}"') == 1
    assert '$("viewerInspectionSource")' not in JS
    assert "function updateViewerInspectionHeader" in JS
    assert '$("viewerModeStatus")?.textContent' in JS
    assert "context?.presentation?.title" in JS


def test_identity_evidence_is_concise_and_payload_driven() -> None:
    assert 'evidence.dataset.summaryLabel=context.verified?"Identity verified":"Identity evidence"' in JS
    assert 'firstCardValue(card,["visual_score","artwork_score"])' in JS
    assert 'context.verified?"Confirmed"' in JS
    assert "content:attr(data-summary-label)" in CSS
    assert ".studiox-identity-evidence>div" in CSS


def test_rareiq_signature_is_static_and_restrained() -> None:
    assert "--premium-signature-gradient" in TOKENS
    assert ".rareiq-orb-signature" in CSS
    assert "giant" not in CSS.lower()
    assert "animation:studioxOrbResolve" in CSS
