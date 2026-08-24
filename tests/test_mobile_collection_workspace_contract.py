from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8-sig")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8-sig")


def collection_mobile_contract() -> str:
    start = CSS.index("/* Mobile Collection owns")
    end = CSS.index("/* Update 6.8.9", start)
    return CSS[start:end]


def test_mobile_collection_uses_one_full_width_content_column() -> None:
    contract = collection_mobile_contract()
    assert '.workspace[data-workspace="collection"] .full-shell' in contract
    assert "grid-template-columns:minmax(0,1fr)!important" in contract
    assert "width:100%!important" in contract
    assert "min-width:0!important" in contract


def test_mobile_collection_navigation_is_horizontal_and_scroll_safe() -> None:
    contract = collection_mobile_contract()
    assert '.workspace[data-workspace="collection"] .side-nav{' in contract
    assert "flex-direction:row!important" in contract
    assert "overflow-x:auto!important" in contract
    assert "overscroll-behavior-x:contain!important" in contract
    assert "scrollbar-width:none!important" in contract
    assert "min-width:102px!important" in contract


def test_collection_structure_and_existing_sections_are_preserved() -> None:
    collection = HTML[
        HTML.index('class="workspace" data-workspace="collection"') :
        HTML.index('class="workspace" data-workspace="broadcast"')
    ]
    assert HTML.count('class="workspace" data-workspace="collection"') == 1
    assert collection.count('class="riq-surface side-nav"') == 1
    for label in ("Recent Scans", "Sessions", "Boxes", "Exports"):
        assert f">{label}</button>" in collection
    for element_id in ("collectionTotal", "collectionUnique", "collectionDuplicates", "librarySyncPanel"):
        assert HTML.count(f'id="{element_id}"') == 1
