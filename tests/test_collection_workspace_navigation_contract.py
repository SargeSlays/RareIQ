from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
DECK = (ROOT / "rareiq/web/static/studiox_command_deck.css").read_text(encoding="utf-8")


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


def test_collection_switch_updates_the_shared_command_deck_context() -> None:
    assert 'id="commandDeckWorkspaceTitle">Live identification</strong>' in HTML
    assert 'id="commandDeckSessionSummary" aria-label="Live identification summary"' in HTML
    assert 'collection:"Collection intelligence"' in JS
    assert 'setCardText("commandDeckWorkspaceTitle",title)' in JS
    assert 'setAttribute("aria-label",`${title} summary`)' in JS
    assert "syncCommandDeckWorkspace(name);" in JS


def test_collection_active_view_uses_the_semantic_brand_accent() -> None:
    start = CSS.index('/* Collection console:')
    collection_styles = CSS[start : CSS.index('.workspace[data-workspace="creator"]', start)]
    assert "var(--ui4-accent-soft" in collection_styles
    assert "var(--ui4-accent,#70e0b9)" in collection_styles
    assert "rgba(117,91,211" not in collection_styles


def test_collection_library_sync_uses_one_brand_progress_language() -> None:
    start = CSS.index(".library-sync-actions")
    library_sync_styles = CSS[start : CSS.index("@media(max-width:1100px)", start)]
    assert "var(--ui4-accent,#70e0b9)" in library_sync_styles
    assert "var(--ui4-surface-muted" in library_sync_styles
    assert "#765dff" not in library_sync_styles
    assert "#28d7ff" not in library_sync_styles


def test_collection_4k_canvas_is_bounded_to_a_readable_working_measure() -> None:
    assert 'width: min(100%, 2200px)' in DECK
    assert '.workspace[data-workspace="collection"] .full-shell > .content > *' in DECK


def test_collection_inventory_forms_use_deterministic_responsive_grids() -> None:
    assert '.workspace[data-workspace="collection"] #inventoryIntakeForm' in DECK
    assert 'grid-template-columns: repeat(12, minmax(0, 1fr)) !important' in DECK
    assert '.workspace[data-workspace="collection"] #inventoryLookupForm' in DECK
    assert 'grid-template-columns: minmax(0, 1fr) auto auto !important' in DECK
    assert '.workspace[data-workspace="collection"] .collection-goal-form' in DECK
    assert '@media (max-width: 1499px)' in DECK
    assert '@media (max-width: 760px)' in DECK
