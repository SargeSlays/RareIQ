from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8-sig")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8-sig")


def both_view_contract() -> str:
    start = CSS.index("/* Mobile Both view keeps")
    end = CSS.index("/* Update 6.8.9", start)
    return CSS[start:end]


def test_both_view_places_identity_and_auto_next_on_one_compact_row() -> None:
    contract = both_view_contract()
    assert '[data-mobile-operator-view="both"] .result-decision-strip' in contract
    assert "display:grid!important" in contract
    assert "grid-template-columns:minmax(0,1fr) auto!important" in contract
    assert "min-width:112px!important" in contract
    assert "height:36px!important" in contract


def test_both_view_keeps_all_decision_actions_visible_on_the_second_row() -> None:
    contract = both_view_contract()
    assert '[data-mobile-operator-view="both"] .result-decision-actions' in contract
    assert "grid-column:1/-1!important" in contract
    assert "grid-auto-rows:36px!important" in contract
    for element_id in (
        "decisionApproveButton",
        "decisionRejectButton",
        "correctMatchButton",
        "decisionNextButton",
    ):
        assert HTML.count(f'id="{element_id}"') == 1


def test_both_view_does_not_hide_or_resize_the_camera_workspace() -> None:
    contract = both_view_contract()
    assert ".camera-workspace" not in contract
    assert "#cameraFeed" not in contract
    assert "object-fit" not in contract
    assert HTML.count('id="cameraFeed"') == 1
