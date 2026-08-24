from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
STYLES = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_creator_rail_is_real_accessible_navigation():
    assert 'id="creatorWorkspaceTabs" role="tablist" aria-label="Creator Studio views"' in CONTROL
    assert CONTROL.count('data-creator-view="') == 3
    for view, panel in (
        ("rules", "creatorRevealConfig"),
        ("live", "creatorRevealMonitor"),
        ("assets", "creatorAssetPanel"),
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
