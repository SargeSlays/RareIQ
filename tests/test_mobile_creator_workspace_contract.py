from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "rareiq" / "web" / "static"
HTML = (STATIC / "control.html").read_text(encoding="utf-8-sig")
CSS = (STATIC / "studiox_update15.css").read_text(encoding="utf-8-sig")


def mobile_creator_contract() -> str:
    start = CSS.index("/* Mobile Creator keeps")
    end = CSS.index("/* Update 6.8.9", start)
    return CSS[start:end]


def test_mobile_creator_uses_two_column_fast_toggle_grid() -> None:
    contract = mobile_creator_contract()
    assert '.workspace[data-workspace="creator"] .creator-reveal-config' in contract
    assert "grid-template-columns:repeat(2,minmax(0,1fr))!important" in contract
    assert '>label:has(input[type="checkbox"])' in contract
    assert "min-height:36px!important" in contract


def test_non_boolean_creator_controls_remain_full_width() -> None:
    contract = mobile_creator_contract()
    assert '>label:not(:has(input[type="checkbox"]))' in contract
    assert "grid-column:1/-1!important" in contract
    assert ".creator-reveal-actions>.riq-button" in contract
    assert "min-height:40px!important" in contract


def test_creator_handlers_and_control_ids_remain_unique() -> None:
    for element_id in (
        "creatorRevealEnabled",
        "creatorBuildSuspense",
        "creatorAudioEnabled",
        "creatorParticlesEnabled",
        "saveRevealSequence",
        "creatorNextPack",
    ):
        assert HTML.count(f'id="{element_id}"') == 1
    assert HTML.count('data-workspace="creator"') == 1
