from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "rareiq" / "web" / "static"
HTML = (STATIC / "control.html").read_text(encoding="utf-8-sig")
CSS = (STATIC / "studiox_update15.css").read_text(encoding="utf-8-sig")


def mobile_utility_contract() -> str:
    start = CSS.index("/* Mobile utility workspaces keep")
    end = CSS.index("/* Update 6.8.9", start)
    return CSS[start:end]


def test_mobile_ai_and_library_overviews_use_readable_single_column_cards() -> None:
    contract = mobile_utility_contract()
    assert '.workspace[data-workspace="ai"]' in contract
    assert '.workspace[data-workspace="library"]' in contract
    assert ".content>.grid" in contract
    assert "grid-template-columns:minmax(0,1fr)!important" in contract
    assert "gap:8px!important" in contract


def test_mobile_library_actions_stay_beside_their_own_card_copy() -> None:
    contract = mobile_utility_contract()
    assert '.workspace[data-workspace="library"] .content>.grid>.card>.riq-button' in contract
    assert "grid-column:2!important" in contract
    assert "grid-row:1/3!important" in contract
    assert "min-height:38px!important" in contract


def test_utility_workspace_ids_and_existing_handlers_remain_unchanged() -> None:
    assert HTML.count('class="workspace" data-workspace="ai"') == 1
    assert HTML.count('class="workspace" data-workspace="library"') == 1
    for endpoint in ("/api/library/optimize", "/api/index/incremental", "/api/providers/check"):
        assert HTML.count(endpoint) == 1
