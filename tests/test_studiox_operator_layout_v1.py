import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "rareiq" / "web" / "static"
HTML = (STATIC / "control.html").read_text(encoding="utf-8-sig")
SCRIPT = (STATIC / "studiox.js").read_text(encoding="utf-8-sig")
BRAND_CSS = (STATIC / "rareiq_brand_v1.css").read_text(encoding="utf-8")
DECK_CSS = (STATIC / "studiox_command_deck.css").read_text(encoding="utf-8")


def test_command_deck_layout_is_versioned_and_enabled() -> None:
    assert 'class="studiox-ui4 studiox-premium studiox-command-deck"' in HTML
    assert 'studiox-operator studiox-command-deck' not in HTML
    assert 'data-operator-layout="v2"' in HTML
    assert 'data-studiox-build="6.9.0-commanddeck67"' in HTML
    assert 'data-studiox-visual-system="unified"' in HTML
    assert '/static/rareiq_brand_v1.css?v=6.9.0-commanddeck67' in HTML
    assert '/static/studiox_command_deck.css?v=6.9.0-commanddeck67' in HTML


def test_operator_layout_preserves_primary_live_contracts() -> None:
    for element_id in (
        "cameraFeed",
        "scanZone",
        "multiCardCameraOverlay",
        "resultDecisionStrip",
        "inspectorSectionNav",
        "cardContextHeader",
        "recognitionSignalPanel",
        "widgetWorkspace",
    ):
        assert HTML.count(f'id="{element_id}"') == 1


def test_command_deck_uses_one_camera_stage_and_one_decision_inspector() -> None:
    assert "--command-deck-rail: 64px" in DECK_CSS
    assert "--command-deck-inspector: clamp(640px, 30vw, 1080px)" in DECK_CSS
    assert "grid-template-columns: var(--command-deck-rail) minmax(0, 1fr) var(--command-deck-inspector)" in DECK_CSS
    assert "article.camera-workspace" in DECK_CSS
    assert ".ui4-inspector-column > .inspector" in DECK_CSS


def test_unified_visual_system_has_complete_dark_and_light_semantic_tokens() -> None:
    unified = DECK_CSS
    assert 'html[data-theme="dark"] body.studiox-command-deck[data-studiox-visual-system="unified"]' in unified
    assert 'html[data-theme="light"] body.studiox-command-deck[data-studiox-visual-system="unified"]' in unified
    for token in (
        "--sx-canvas",
        "--sx-chrome",
        "--sx-surface",
        "--sx-surface-raised",
        "--sx-divider",
        "--sx-text",
        "--sx-text-soft",
        "--sx-accent",
        "--sx-warning",
        "--sx-danger",
    ):
        assert unified.count(token) >= 2


def test_unified_visual_system_uses_obsidian_slate_depth_palette() -> None:
    for declaration in (
        "--sx-canvas: #07090d",
        "--sx-chrome: #0b1016",
        "--sx-surface: #111821",
        "--sx-surface-raised: #18222e",
        "--sx-surface-muted: #1c2835",
        "--sx-surface-hover: #202d3b",
        "--sx-divider: #293747",
        "--sx-divider-strong: #3a4b60",
        "--sx-text: #f4f7fa",
        "--sx-text-soft: #b5c0cc",
        "--sx-text-muted: #778493",
        "--sx-accent: #8be8ca",
        "--sx-active: #4b9fff",
        "--sx-warning: #f2b84b",
        "--sx-danger: #ed6a70",
    ):
        assert declaration in DECK_CSS

    for declaration in (
        "--sx-canvas: #eef2f4",
        "--sx-chrome: #f8fafb",
        "--sx-surface: #ffffff",
        "--sx-surface-raised: #f5f8fa",
        "--sx-surface-muted: #e7edf1",
        "--sx-surface-hover: #dee7ed",
        "--sx-divider: #c7d2dc",
        "--sx-divider-strong: #9eafbf",
        "--sx-text: #17212b",
        "--sx-accent: #187f66",
        "--sx-active: #2d78d4",
    ):
        assert declaration in DECK_CSS

    assert "background: var(--sx-active-soft) !important" in DECK_CSS
    assert "box-shadow: inset 3px 0 0 var(--sx-active) !important" in DECK_CSS


def test_unified_navigation_is_monochrome_and_uses_one_active_signal() -> None:
    unified = DECK_CSS
    assert '.ui4-navigation-rail .nav-app-icon svg *' in unified
    assert "stroke: currentColor !important" in unified
    assert "fill: none !important" in unified
    assert "box-shadow: inset 3px 0 0 var(--sx-active) !important" in unified
    assert 'content: attr(aria-label)' in unified


def test_unified_inspector_is_one_surface_with_sectional_dividers() -> None:
    unified = DECK_CSS
    assert ".ui4-inspector-column > .inspector" in unified
    assert "border-radius: 0 !important" in unified
    assert "background: var(--sx-surface) !important" in unified
    assert "border-bottom: 1px solid var(--sx-divider) !important" in unified
    assert "#widgetWorkspace > .studiox-widget" in unified


def test_command_deck_has_one_header_and_two_explicit_drawers() -> None:
    assert HTML.count('class="command-deck-session"') == 1
    assert HTML.count('class="command-deck-actions"') == 1
    assert HTML.count('id="scanSetupDrawer"') == 1
    assert HTML.count('id="productionControlsDrawer"') == 1
    assert 'aria-controls="scanSetupDrawer"' in HTML
    assert 'aria-controls="productionControlsDrawer"' in HTML
    assert 'body.studiox-ui4.studiox-premium.studiox-command-deck[data-operator-layout="v2"][data-command-deck-panel="setup"] #scanSetupDrawer' in DECK_CSS
    assert 'body.studiox-ui4.studiox-premium.studiox-command-deck[data-operator-layout="v2"][data-command-deck-panel="production"] #productionControlsDrawer' in DECK_CSS


def test_inspector_navigation_switches_views_instead_of_scrolling_to_panels() -> None:
    assert 'const operatorInspectorSections={cardContextHeader:"card",recognitionSignalPanel:"signals",widgetWorkspace:"tools"}' in SCRIPT
    assert "inspector.dataset.operatorSection=section" in SCRIPT
    assert 'currentView.scrollTo({top:0,behavior:"auto"})' in SCRIPT
    assert 'setOperatorInspectorSection(inspectorSectionNav?.querySelector(\'[data-inspector-section="cardContextHeader"]\'))' in SCRIPT


def test_operator_inspector_tabs_remain_keyboard_accessible() -> None:
    assert '["ArrowLeft","ArrowRight","Home","End"].includes(event.key)' in SCRIPT
    assert 'item.setAttribute("aria-pressed",String(selected))' in SCRIPT
    assert "setOperatorInspectorSection(buttons[next],{focus:true})" in SCRIPT


def test_operator_views_keep_all_existing_surfaces_available() -> None:
    assert '.inspector[data-operator-section="card"] #recognitionSignalPanel' in DECK_CSS
    assert '.inspector[data-operator-section="card"] #widgetWorkspace' in DECK_CSS
    assert '.inspector[data-operator-section="card"] #widgetWorkspace > :not(:is(' in DECK_CSS
    assert '[data-studiox-widget="identify"],' in DECK_CSS
    assert '[data-studiox-widget="pokedex"]' in DECK_CSS
    assert '.inspector[data-operator-section="signals"] #recognitionSignalPanel' in DECK_CSS
    assert '.inspector[data-operator-section="tools"] #widgetWorkspace' in DECK_CSS
    assert "display: grid !important" in DECK_CSS


def test_card_view_pairs_identity_with_rare_intelligence() -> None:
    assert HTML.count('data-studiox-widget="pokedex"') == 1
    assert 'aria-label="Rare Intelligence character and species profile"' in HTML
    assert '.inspector[data-operator-section="card"] [data-studiox-widget="pokedex"]' in DECK_CSS
    assert '[data-studiox-widget="pokedex"] .studiox-pokedex-content' in DECK_CSS
    assert "grid-template-areas:" in DECK_CSS
    assert '"art profile facts"' in DECK_CSS
    assert 'Rare Intelligence for ${pendingName} will appear after identity verification.' in SCRIPT
    assert 'hidden:validList(value.hidden).filter(id=>id!=="pokedex")' in SCRIPT
    assert 'collapsed:validList(value.collapsed).filter(id=>id!=="pokedex")' in SCRIPT


def test_command_deck_prevents_inspector_overlap_and_legacy_health_clutter() -> None:
    assert "flex: 0 0 auto !important" in DECK_CSS
    assert ".ui4-health-popover" in DECK_CSS
    assert ".ui4-app-health" in DECK_CSS
    assert ".inspector-secondary-actions" in DECK_CSS
    assert "display: none !important" in DECK_CSS


def test_command_deck_uses_one_verdict_and_a_compact_verification_pipeline() -> None:
    assert '"identity auto"' in DECK_CSS
    assert '"identity actions"' in DECK_CSS
    assert "grid-area: auto !important" in DECK_CSS
    assert "grid-area: actions !important" in DECK_CSS
    assert ".studiox-live-analysis-head > div > strong" in DECK_CSS
    assert ".studiox-live-analysis-head > b" in DECK_CSS
    assert "grid-template-columns: repeat(5, minmax(0, 1fr)) !important" in DECK_CSS


def test_card_view_keeps_diagnostics_available_without_letting_them_dominate() -> None:
    assert '.inspector[data-operator-section="card"] #recognitionSignalPanel :is(' in DECK_CSS
    assert "#recognitionLatencyTrace" in DECK_CSS
    assert "#referenceCacheMetrics" in DECK_CSS
    assert "#packSpeedMetrics" in DECK_CSS
    assert '.inspector[data-operator-section="signals"] #recognitionSignalPanel' in DECK_CSS


def test_right_rail_matches_the_flat_command_bar_architecture() -> None:
    assert ".ui4-top-app-bar" in DECK_CSS
    assert "padding: 8px 24px !important" in DECK_CSS
    assert ".ui4-inspector-column > .inspector" in DECK_CSS
    assert "border-radius: 0 !important" in DECK_CSS
    assert ".ui4-inspector-primary-tabs button[aria-selected=\"true\"]" in DECK_CSS
    assert "box-shadow: inset 0 -2px var(--sx-active) !important" in DECK_CSS
    assert ".studiox-identity-evidence > div" in DECK_CSS
    assert ".recognition-signal-panel .signal" in DECK_CSS
    assert "border-bottom: 1px solid var(--sx-divider) !important" in DECK_CSS


def test_right_rail_controls_have_one_spaced_runtime_action_layout() -> None:
    assert "/* Final inspector ownership: spacing and controls resolve here, once. */" in DECK_CSS
    assert DECK_CSS.count("/* Final inspector ownership: spacing and controls resolve here, once. */") == 1
    assert "Continuous inspector composition" not in DECK_CSS
    assert "grid-template-columns: repeat(auto-fit, minmax(72px, 1fr)) !important" in DECK_CSS
    assert "gap: var(--sx-control-gap) !important" in DECK_CSS
    assert "grid-template-columns: minmax(220px, 1fr) clamp(280px, 36%, 420px) !important" in DECK_CSS
    assert "border: 1px solid var(--sx-divider-strong) !important" in DECK_CSS
    assert 'decisionActions.insertBefore(correctMatch,$("decisionNextButton"))' in SCRIPT


def test_wide_inspector_reclaims_vertical_space_without_hiding_information() -> None:
    assert "min-height: 132px !important" in DECK_CSS
    assert "min-height: 86px !important" in DECK_CSS
    assert "grid-template-rows: 24px minmax(28px, auto) 14px !important" in DECK_CSS
    assert "#recognitionSignalPanel .recognition-signal-title" in DECK_CSS
    assert "#inspectorMain #widgetWorkspace" in DECK_CSS


def test_camera_utility_strip_is_unclipped_and_right_rail_keeps_tonal_depth() -> None:
    assert "article.camera-workspace .viewer-inspection-header" in DECK_CSS
    assert "grid-template-columns: 130px minmax(240px, 360px) minmax(140px, 180px) minmax(0, 1fr) !important" in DECK_CSS
    assert "overflow: visible !important" in DECK_CSS
    assert "border-radius: 0 !important" in DECK_CSS
    assert "#recognitionSignalPanel" in DECK_CSS
    assert "background: var(--sx-surface-raised) !important" in DECK_CSS
    assert "#widgetWorkspace > .studiox-widget.is-focused" in DECK_CSS
    assert "box-shadow: inset 3px 0 0 var(--sx-accent) !important" in DECK_CSS


def test_camera_layout_and_control_toolbar_remain_persistently_available() -> None:
    assert '>Camera Controls</button>' in HTML
    assert 'id="productionControlsDrawer" role="region" aria-label="Camera workspace controls" aria-hidden="false"' in HTML
    assert "--command-deck-camera-toolbar-height: 68px" in DECK_CSS
    assert "#productionControlsDrawer" in DECK_CSS
    assert "opacity: 1 !important" in DECK_CSS
    assert "visibility: visible !important" in DECK_CSS
    assert "pointer-events: auto !important" in DECK_CSS
    assert "productionPersistent=window.matchMedia(\"(min-width: 960px)\").matches" in SCRIPT
    assert 'querySelector("button, select")?.focus()' in SCRIPT
    for layout in ("single", "dual-side", "triple", "quad"):
        assert HTML.count(f'data-camera-layout-option="{layout}"') == 1


def test_right_rail_uses_one_continuous_surface_with_clear_section_bands() -> None:
    assert "#inspectorMain" in DECK_CSS
    assert "padding: 10px 16px 18px !important" in DECK_CSS
    assert "background: var(--sx-surface) !important" in DECK_CSS
    assert ".studiox-live-analysis," in DECK_CSS
    assert ".studiox-identity-pending," in DECK_CSS
    assert "#recognitionSignalPanel" in DECK_CSS
    assert "border-bottom: 1px solid var(--sx-divider) !important" in DECK_CSS
    assert "border-radius: 0 !important" in DECK_CSS
    assert "box-shadow: none !important" in DECK_CSS
    assert "right: calc(var(--command-deck-inspector) + 16px) !important" in DECK_CSS


def test_candidate_decision_uses_the_existing_control_surface_without_nested_card_chrome() -> None:
    assert ".single-card-control > .result-decision-strip" in DECK_CSS
    assert "border-bottom: 1px solid var(--sx-divider) !important" in DECK_CSS
    assert "background: transparent !important" in DECK_CSS


def test_decision_console_tabs_and_live_analysis_form_one_production_flow() -> None:
    assert ".result-decision-strip::before" in DECK_CSS
    assert "border-left: 1px solid var(--sx-divider) !important" in DECK_CSS
    assert "#decisionVerdict" in DECK_CSS
    assert "grid-template-columns: repeat(3, minmax(0, 1fr)) !important" in DECK_CSS
    assert ".inspector-section-nav button[aria-current=\"true\"]" in DECK_CSS
    assert ".studiox-live-analysis li::after" in DECK_CSS
    assert ".studiox-live-analysis li[data-step-state=\"complete\"]::after" in DECK_CSS
    assert ".studiox-live-analysis li[data-step-state=\"active\"] > i" in DECK_CSS
    assert "@keyframes commandDeckFlowPulse" in DECK_CSS
    assert "@media (prefers-reduced-motion: reduce)" in DECK_CSS


def test_camera_offline_state_replaces_stale_verification_presentation() -> None:
    assert 'title:"CAMERA OFFLINE"' in SCRIPT
    assert 'placeholderTitle:"Camera Offline"' in SCRIPT
    assert '!["ready","exact-match"].includes(state)&&!unavailable' in SCRIPT
    assert '$("identityPendingTitle").textContent=unavailable?"CAMERA OFFLINE":"IDENTITY PENDING"' in SCRIPT
    assert 'if(signalPanel) signalPanel.hidden=unavailable' in SCRIPT
    assert 'if(autoNext) autoNext.hidden=unavailable' in SCRIPT
    assert 'verdictBadge&&!verdictBadge.hidden?verdictBadge.textContent?.trim():""' in SCRIPT
    assert '.auto-add-verified-control[hidden]' in DECK_CSS
    assert '#recognitionSignalPanel[hidden]' in DECK_CSS


def test_identify_widget_has_truthful_offline_and_ready_copy() -> None:
    for element_id in (
        "identifyEvidenceEyebrow",
        "identifyEvidenceTitle",
        "identifyEvidenceDetail",
    ):
        assert HTML.count(f'id="{element_id}"') == 1
    assert 'unavailable?"Recognition paused"' in SCRIPT
    assert 'unavailable?"Camera offline"' in SCRIPT
    assert '"Reconnect a camera to resume identity checks."' in SCRIPT
    assert 'if(reviewButton) reviewButton.hidden=unavailable||!context.card' in SCRIPT
    assert 'unavailable\n      ?"error"' in SCRIPT


def test_command_deck_has_one_authoritative_style_layer() -> None:
    assert "studiox-operator" not in BRAND_CSS
    assert "Studio X Command Deck v2" not in BRAND_CSS
    assert "Studio X unified visual system" not in BRAND_CSS
    assert "Specificity lock" not in BRAND_CSS
    assert DECK_CSS.count("Authoritative desktop presentation") == 1
    assert "ui4-unified-card-stage-overrides" not in HTML
    assert "<style" not in HTML
    assert HTML.count("<div") == HTML.count("</div>")


def test_operator_redesign_adds_no_new_polling_or_backend_contract() -> None:
    section = SCRIPT[
        SCRIPT.index("const operatorInspectorSections=") :
        SCRIPT.index('if($("inspectorEmpty"))', SCRIPT.index("const operatorInspectorSections="))
    ]
    assert "fetch(" not in section
    assert "setInterval(" not in section
    assert "/api/" not in section


def test_command_deck_reuses_primary_capture_and_existing_controls() -> None:
    assert HTML.count("premium-capture-action") == 1
    assert 'if(target===deckActions)target.append(primaryCapture);else target.prepend(primaryCapture)' in SCRIPT
    assert 'window.matchMedia("(min-width: 960px)").matches?deckActions:legacyActions' in SCRIPT
    assert 'workflowPrompt.parentElement!==camera' in SCRIPT
    assert 'camera.appendChild(workflowPrompt)' in SCRIPT
    assert 'function setCommandDeckPanel(panel)' in SCRIPT
    command_deck = SCRIPT[
        SCRIPT.index("function syncCommandDeckSummary") :
        SCRIPT.index("function initializeStudioXUI4")
    ]
    assert "fetch(" not in command_deck
    assert "setInterval(" not in command_deck
    assert "/api/" not in command_deck


def test_command_deck_drawers_are_keyboard_and_pointer_safe() -> None:
    assert 'event.key==="Escape"&&document.body.dataset.commandDeckPanel' in SCRIPT
    assert 'setAttribute("aria-expanded",String(setupOpen))' in SCRIPT
    assert 'setAttribute("aria-hidden",String(!setupOpen))' in SCRIPT
    assert 'if(drawer&&!drawer.contains(event.target)&&!trigger?.contains(event.target))setCommandDeckPanel("")' in SCRIPT


def test_every_left_rail_app_uses_the_shared_branded_workspace_shell() -> None:
    app_names = (
        "collection",
        "broadcast",
        "creator",
        "soundboard",
        "voice-mod",
        "camera-fx",
        "spotify",
        "ai",
        "library",
        "settings",
    )
    shared_apps = re.findall(
        r'<section class="[^"]*\bstudiox-app-workspace\b[^"]*" data-workspace="([^"]+)">',
        HTML,
    )
    assert tuple(shared_apps) == app_names
    assert HTML.count("studiox-app-heading") >= len(app_names)
    assert HTML.count("studiox-app-eyebrow") >= len(app_names)
    for app_name in app_names:
        assert f'data-target="{app_name}"' in HTML
        assert re.search(
            rf'<section class="[^"]*studiox-app-workspace[^"]*" data-workspace="{re.escape(app_name)}">',
            HTML,
        )


def test_shared_app_shell_matches_live_homepage_hierarchy_without_new_runtime_contracts() -> None:
    assert "/* Unified application workspaces" in DECK_CSS
    assert ".studiox-app-workspace .full-shell" in DECK_CSS
    assert ".studiox-app-workspace .full-shell > .side-nav" in DECK_CSS
    assert ".studiox-app-heading" in DECK_CSS
    assert ".studiox-app-heading .studiox-app-eyebrow" in DECK_CSS
    assert ".studiox-app-workspace :is(input, select, textarea, button, a):focus-visible" in DECK_CSS
    assert ".studiox-app-workspace--broadcast > .broadcast-workspace-tabs" in DECK_CSS
    assert ".studiox-app-workspace--broadcast.active" in DECK_CSS
    assert '.studiox-app-workspace--broadcast {\n  display: grid !important' not in DECK_CSS
    assert '.workspace[data-workspace="spotify"].active' in DECK_CSS
    assert '.workspace[data-workspace="spotify"] .spotify-shell' in DECK_CSS
    assert "display: contents !important" in DECK_CSS
    assert ".studiox-app-workspace > .workspace-readiness" in DECK_CSS
    assert ".workspace[data-workspace=\"collection\"] :is(" in DECK_CSS
    assert '[data-ui4-workspace]:not([data-ui4-workspace="live"]) .ui4-desktop-shell' in DECK_CSS
    assert '[data-ui4-workspace]:not([data-ui4-workspace="live"]) .ui4-inspector-column' in DECK_CSS


def test_left_rail_app_shell_has_no_duplicate_dom_ids() -> None:
    ids = re.findall(r'\bid="([^"]+)"', HTML)
    duplicates = {element_id: count for element_id, count in Counter(ids).items() if count > 1}
    assert duplicates == {}
