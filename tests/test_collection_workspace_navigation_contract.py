from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_collection_rail_is_an_accessible_four_view_tablist() -> None:
    assert HTML.count('id="collectionWorkspaceTabs"') == 1
    assert 'role="tablist" aria-label="Collection workspace views"' in HTML
    for view, label in (
        ("recent", "Recent Scans"),
        ("sessions", "Sessions"),
        ("boxes", "Boxes"),
        ("exports", "Exports"),
    ):
        assert HTML.count(f'data-collection-view="{view}"') == 1
        assert f">{label}</button>" in HTML


def test_collection_views_route_existing_modules_without_new_data_calls() -> None:
    section = JS[JS.index("const COLLECTION_WORKSPACE_PANELS") : JS.index("const BROADCAST_WORKSPACE_PANELS")]
    for selector in (
        "#librarySyncPanel",
        ".collection-exact-inventory",
        ".inventory-pack-ledgers",
        ".approved-inventory-intake",
        ".collection-set-progress",
        ".inventory-listing-dashboard",
        ".accounting-controls",
        ".collection-recovery",
    ):
        assert selector in section
    assert "fetch(" not in section
    assert "api(" not in section


def test_collection_view_selection_is_persistent_and_keyboard_accessible() -> None:
    assert "function setCollectionWorkspaceView" in JS
    assert "function initializeCollectionWorkspace" in JS
    assert "localStorage.setItem(COLLECTION_WORKSPACE_VIEW_KEY,view)" in JS
    assert 'localStorage.getItem(COLLECTION_WORKSPACE_VIEW_KEY)||"recent"' in JS
    for key in ("ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End"):
        assert f'"{key}"' in JS


def test_collection_view_hiding_and_active_state_are_explicit() -> None:
    assert 'panel.hidden=!panel.dataset.collectionPanels.split(" ").includes(view)' in JS
    assert '[data-collection-panels][hidden]{display:none!important}' in CSS
    assert '[data-collection-view][aria-selected="true"]' in CSS
    assert 'html[data-theme="light"] .workspace[data-workspace="collection"]' in CSS


def test_collection_heading_tracks_the_selected_operator_view() -> None:
    assert '"Session & Pack Intelligence"' in JS
    assert '"Physical Inventory & Boxes"' in JS
    assert '"Marketplace & Exports"' in JS
    assert 'heading.querySelector("h2").textContent=title' in JS
