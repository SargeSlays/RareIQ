from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
STYLES = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
DECK = (ROOT / "rareiq/web/static/studiox_command_deck.css").read_text(encoding="utf-8")


def test_creator_rail_is_real_accessible_navigation():
    assert 'id="creatorWorkspaceTabs" role="tablist" aria-label="Creator Studio views"' in CONTROL
    assert CONTROL.count('data-creator-view="') == 4
    for view, panel in (
        ("rules", "creatorRevealConfig"),
        ("live", "creatorRevealMonitor"),
        ("assets", "creatorAssetPanel"),
        ("chase", "creatorChasePanel"),
    ):
        assert f'data-creator-view="{view}"' in CONTROL
        assert f'aria-controls="{panel}"' in CONTROL
        assert f'id="{panel}" role="tabpanel"' in CONTROL


def test_creator_navigation_preserves_existing_tool_handlers():
    for element_id in (
        "saveRevealSequence",
        "creatorNextPack",
        "creatorRevealNow",
        "creatorCancelReveal",
        "creatorAssetUpload",
        "creatorTierMapping",
    ):
        assert f'id="{element_id}"' in CONTROL
        assert f'$("{element_id}")' in SCRIPT or element_id in SCRIPT


def test_creator_view_selection_is_persistent_and_keyboard_accessible():
    assert 'const CREATOR_WORKSPACE_VIEW_KEY="rareiq.creator.workspace.view.v1"' in SCRIPT
    assert "function setCreatorWorkspaceView" in SCRIPT
    assert "function initializeCreatorWorkspace" in SCRIPT
    assert 'initializeCreatorWorkspace();' in SCRIPT
    for key in ("ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End"):
        assert f'"{key}"' in SCRIPT
    assert "localStorage.setItem(CREATOR_WORKSPACE_VIEW_KEY,view)" in SCRIPT


def test_creator_views_are_exclusive_without_changing_layout_contracts():
    assert 'layout.hidden=view==="assets"' in SCRIPT
    assert 'config.hidden=view!=="rules"' in SCRIPT
    assert 'monitor.hidden=view!=="live"' in SCRIPT
    assert 'assets.hidden=view!=="assets"' in SCRIPT
    assert '.workspace[data-workspace="creator"] .creator-reveal-layout{grid-template-columns:minmax(0,1fr)}' in STYLES
    assert '[data-creator-view][aria-selected="true"]' in STYLES


def test_creator_default_view_is_reveal_rules():
    assert 'data-creator-view="rules" aria-selected="true"' in CONTROL
    assert 'id="creatorRevealMonitor" role="tabpanel" aria-labelledby="creatorTabLive" tabindex="0" hidden' in CONTROL
    assert 'id="creatorAssetPanel" role="tabpanel" aria-labelledby="creatorTabAssets" tabindex="0" hidden' in CONTROL


def test_creator_heading_tracks_the_selected_operator_view():
    assert 'heading=content?.querySelector(".studiox-app-heading")' in SCRIPT
    assert 'heading.querySelector("h2").textContent=title' in SCRIPT
    assert 'heading.querySelector("p").textContent=description' in SCRIPT
    assert 'content?.querySelector(":scope>h2")' not in SCRIPT


def test_creator_command_deck_removes_legacy_reveal_chrome():
    creator_start = DECK.index("/* Creator */")
    creator_end = DECK.index("/* Soundboard */", creator_start)
    creator = DECK[creator_start:creator_end]
    for selector in (
        ".creator-reveal-monitor > strong",
        ".collection-progress-track",
        "#creatorSuspenseBar",
        ".creator-sequence-slots i",
        ".creator-hit-decision",
        ".creator-reaction-preview",
        ".creator-asset-row",
        ".creator-tier-card",
    ):
        assert selector in creator
    assert "background-image: none !important" in creator
    assert "var(--sx-surface-muted)" in creator
    assert "var(--sx-accent)" in creator
    assert "var(--sx-warning)" in creator
    assert "#61ddf8" not in creator
    assert "#a77aff" not in creator
    assert "border-radius: 999px" not in creator


def test_creator_command_deck_uses_compact_production_layouts():
    creator_start = DECK.index("/* Creator */")
    creator_end = DECK.index("/* Soundboard */", creator_start)
    creator = DECK[creator_start:creator_end]
    assert "grid-template-columns: repeat(3, minmax(0, 1fr)) !important" in creator
    assert ':is(.creator-reveal-config, .creator-reveal-monitor, .creator-assets)[hidden]' in creator
    assert '.creator-reveal-config > label:has(input[type="checkbox"])' in creator
    assert "grid-template-columns: repeat(10, minmax(28px, 1fr)) !important" in creator
    assert "grid-template-columns: repeat(4, minmax(0, 1fr)) !important" in creator
    assert "max-height: 160px !important" in creator


def test_creator_owns_the_wide_operator_stage_without_a_centered_content_cap():
    creator_start = DECK.index("/* Creator */")
    creator_end = DECK.index("/* Soundboard */", creator_start)
    creator = DECK[creator_start:creator_end]
    assert "@media (min-width: 1800px)" in creator
    assert '.workspace[data-workspace="creator"] > .full-shell' in creator
    assert "width: 100% !important" in creator
    assert "max-width: none !important" in creator
    assert "grid-template-columns: repeat(5, minmax(0, 1fr)) !important" in creator
    assert "grid-template-columns: repeat(12, minmax(0, 1fr)) !important" in creator
    assert ".creator-reveal-monitor > .creator-hit-decision" in creator
    assert ".creator-reveal-monitor > .creator-reaction-preview" in creator
    assert "grid-template-columns: repeat(6, minmax(0, 1fr)) !important" in creator


def test_creator_chase_uses_available_height_and_one_persistent_editor():
    assert 'id="creatorChaseFrame" data-src="/creator/set-chase?embed=creator"' in CONTROL
    assert 'height:1300px' not in CONTROL
    assert '!chaseFrame.hasAttribute("src")' in SCRIPT
    assert '.workspace[data-workspace="creator"][data-creator-view="chase"] .full-shell > .content' in DECK
    assert ':is(.creator-reveal-layout, #creatorChasePanel)[hidden]' in DECK
    frame = DECK.split('#creatorChaseFrame {', 1)[1].split('}', 1)[0]
    assert 'flex: 1 1 0' in frame and 'min-height: 0' in frame
