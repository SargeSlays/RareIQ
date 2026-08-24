from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8-sig")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8-sig")


def mobile_card_contract() -> str:
    return CSS[CSS.index("/* Mobile card inspector density") :]


def test_mobile_decision_strip_does_not_inherit_desktop_vertical_flex_bases() -> None:
    contract = mobile_card_contract()
    assert "flex-direction:column!important" in contract
    assert "flex-wrap:nowrap!important" in contract
    assert "height:auto!important" in contract
    assert ".result-decision-identity{flex:0 0 auto!important}" in contract
    assert ".result-decision-actions{flex:0 0 40px!important" in contract


def test_mobile_decision_actions_remain_visible_and_touchable() -> None:
    contract = mobile_card_contract()
    assert ".result-decision-actions button{height:40px!important}" in contract
    assert "display:none" not in contract[contract.index(".result-decision-actions{") : contract.index(".result-decision-actions button")]
    for element_id in (
        "decisionApproveButton",
        "decisionRejectButton",
        "correctMatchButton",
        "decisionNextButton",
    ):
        assert HTML.count(f'id="{element_id}"') == 1


def test_mobile_auto_next_control_is_compact_but_preserved() -> None:
    contract = mobile_card_contract()
    assert ".auto-add-verified-control{flex:0 0 40px!important" in contract
    assert ".auto-add-verified-control input{width:16px!important;height:16px!important" in contract
    assert HTML.count('id="autoAddVerifiedEnabled"') == 1
