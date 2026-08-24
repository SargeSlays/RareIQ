from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_mobile_workspace_switch_has_three_native_buttons_and_default_both():
    assert 'aria-label="Mobile workspace view"' in HTML
    for view, pressed in (("camera", "false"), ("both", "true"), ("card", "false")):
        assert f'data-mobile-operator-view="{view}" aria-pressed="{pressed}"' in HTML
    assert HTML.count('data-mobile-operator-view="camera"') == 1
    assert HTML.count('data-mobile-operator-view="both"') == 1
    assert HTML.count('data-mobile-operator-view="card"') == 1


def test_switch_only_changes_mobile_presentation_and_keeps_both_as_safe_fallback():
    function = JS[JS.index("function setMobileOperatorView") : JS.index("function syncResultDecisionStrip")]
    assert '["camera","both","card"].includes(requested)?requested:"both"' in function
    assert 'document.querySelectorAll(".mobile-operator-view-switcher [data-mobile-operator-view]")' in function
    assert "loadRecognition" not in function
    assert "captureRecognitionMode" not in function
    assert "newestRecognitionRevision" not in function


def test_portrait_focus_rules_hide_only_the_unselected_existing_surface():
    marker = '@media(max-width:959px) and (orientation:portrait)'
    section = CSS[CSS.index(marker) : CSS.index("/* Update 6.8.9 — short landscape operator mode.")]
    assert '[data-mobile-operator-view="camera"] .ui4-inspector-column{display:none!important}' in section
    assert '[data-mobile-operator-view="card"] .ui4-center-column{display:none!important}' in section
    assert "#cameraFeed" not in section
    assert "visibility:hidden" not in section


def test_landscape_hides_the_switch_and_keeps_both_workspaces_visible():
    section = CSS[CSS.index("/* Update 6.8.9 — short landscape operator mode.") :]
    assert ".mobile-operator-view-switcher{display:none!important}" in section
    assert ".ui4-center-column" in section and ".ui4-inspector-column" in section
