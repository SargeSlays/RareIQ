from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8-sig")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8-sig")


def compact_card_contract() -> str:
    start = CSS.index("/* Mobile Card and Both views keep")
    end = CSS.index("/* Mobile Recent Scans is a bounded", start)
    return CSS[start:end]


def test_card_and_both_views_share_the_compact_decision_grid() -> None:
    contract = compact_card_contract()
    selector = ':is([data-mobile-operator-view="both"],[data-mobile-operator-view="card"])'
    assert selector in contract
    assert "grid-template-columns:minmax(0,1fr) auto!important" in contract
    assert "grid-column:1/-1!important" in contract
    assert "grid-auto-rows:36px!important" in contract


def test_card_view_keeps_identity_automation_and_all_actions() -> None:
    contract = compact_card_contract()
    for selector in (
        ".result-decision-identity",
        ".auto-add-verified-control",
        ".result-decision-actions",
        ".card-removal-progress",
    ):
        assert selector in contract
    for element_id in (
        "decisionApproveButton",
        "decisionRejectButton",
        "correctMatchButton",
        "decisionNextButton",
        "autoAddVerifiedEnabled",
    ):
        assert HTML.count(f'id="{element_id}"') == 1


def test_card_view_does_not_change_current_card_content_or_camera_geometry() -> None:
    contract = compact_card_contract()
    assert ".ui4-current-card-view" not in contract
    assert ".camera-workspace" not in contract
    assert "#cameraFeed" not in contract
    assert HTML.count('id="cameraFeed"') == 1
