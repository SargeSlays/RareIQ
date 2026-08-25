from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "rareiq" / "web" / "static"
HTML = (STATIC / "control.html").read_text(encoding="utf-8-sig")
SCRIPT = (STATIC / "studiox.js").read_text(encoding="utf-8-sig")
BRAND_CSS = (STATIC / "rareiq_brand_v1.css").read_text(encoding="utf-8")


def test_operator_layout_is_versioned_and_enabled() -> None:
    assert 'class="studiox-ui4 studiox-premium studiox-operator"' in HTML
    assert 'data-operator-layout="v1"' in HTML
    assert 'data-studiox-build="6.8.99-operator1"' in HTML
    assert '/static/rareiq_brand_v1.css?v=6.8.99-operator1' in HTML


def test_operator_layout_preserves_primary_live_contracts() -> None:
    for element_id in (
        "cameraFeed",
        "scanZone",
        "multiCardCameraOverlay",
        "resultDecisionStrip",
        "inspectorSectionNav",
        "cardContextHeader",
        "recognitionSignalPanel",
        "widgetWorkspace",
    ):
        assert HTML.count(f'id="{element_id}"') == 1


def test_operator_shell_uses_one_camera_stage_and_one_decision_inspector() -> None:
    assert "--operator-rail-width: 76px" in BRAND_CSS
    assert "--operator-inspector-width: clamp(460px, 28vw, 1080px)" in BRAND_CSS
    assert "grid-template-columns: var(--operator-rail-width) minmax(0, 1fr) var(--operator-inspector-width)" in BRAND_CSS
    assert "article.camera-workspace" in BRAND_CSS
    assert ".ui4-inspector-column > .inspector" in BRAND_CSS


def test_operator_header_has_no_absolute_or_negative_margin_layout_hacks() -> None:
    operator_css = BRAND_CSS.split("Studio X Operator layout v1", 1)[1]
    command_css = operator_css.split(".workspace-stage", 1)[0]
    assert "position: absolute" not in command_css
    assert "margin: -" not in command_css
    assert "grid-template-columns: 216px minmax(0, 1fr)" in command_css


def test_inspector_navigation_switches_views_instead_of_scrolling_to_panels() -> None:
    assert 'const operatorInspectorSections={cardContextHeader:"card",recognitionSignalPanel:"signals",widgetWorkspace:"tools"}' in SCRIPT
    assert "inspector.dataset.operatorSection=section" in SCRIPT
    assert 'currentView.scrollTo({top:0,behavior:"auto"})' in SCRIPT
    assert 'setOperatorInspectorSection(inspectorSectionNav?.querySelector(\'[data-inspector-section="cardContextHeader"]\'))' in SCRIPT


def test_operator_inspector_tabs_remain_keyboard_accessible() -> None:
    assert '["ArrowLeft","ArrowRight","Home","End"].includes(event.key)' in SCRIPT
    assert 'item.setAttribute("aria-pressed",String(selected))' in SCRIPT
    assert "setOperatorInspectorSection(buttons[next],{focus:true})" in SCRIPT


def test_operator_views_keep_all_existing_surfaces_available() -> None:
    assert '.inspector[data-operator-section="card"] #recognitionSignalPanel' in BRAND_CSS
    assert '.inspector[data-operator-section="signals"] #recognitionSignalPanel' in BRAND_CSS
    assert '.inspector[data-operator-section="tools"] #widgetWorkspace' in BRAND_CSS
    assert "display: grid !important" in BRAND_CSS


def test_operator_redesign_adds_no_new_polling_or_backend_contract() -> None:
    section = SCRIPT[
        SCRIPT.index("const operatorInspectorSections=") :
        SCRIPT.index('if($("inspectorEmpty"))', SCRIPT.index("const operatorInspectorSections="))
    ]
    assert "fetch(" not in section
    assert "setInterval(" not in section
    assert "/api/" not in section
