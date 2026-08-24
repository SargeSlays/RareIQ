from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8-sig")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8-sig")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8-sig")


def test_broadcast_console_has_seven_accessible_operator_views() -> None:
    assert HTML.count('id="broadcastWorkspaceTabs"') == 1
    assert 'role="tablist" aria-label="Broadcast workspace views"' in HTML
    for view, label in (
        ("live", "Live Control"),
        ("destinations", "Destinations"),
        ("show", "Run of Show"),
        ("graphics", "Graphics"),
        ("insights", "Insights"),
        ("history", "History"),
        ("setup", "Setup"),
    ):
        assert HTML.count(f'data-broadcast-view="{view}"') == 1
        assert f">{label}</button>" in HTML
    assert 'data-broadcast-view="live" aria-selected="true"' in HTML


def test_every_existing_broadcast_module_is_assigned_to_one_view() -> None:
    mapping = JS[JS.index("const BROADCAST_WORKSPACE_PANELS") : JS.index("function setBroadcastWorkspaceView")]
    for selector in (
        ".production-session-metadata", ".break-history-controls", ".break-history",
        ".production-report-actions", ".pack-economics", ".pack-tracker",
        ".card-show-analytics", ".show-analytics", ".obs-diagnostic",
        ".obs-bootstrap", ".obs-control", ".encoder-guide", ".recording-settings",
        ".production-session", ".operator-health", ".show-preflight",
        ".rundown-safety", ".rundown-library", ".rundown-preflight",
        ".production-rundown", ".production-switcher-shell", ".production-scenes",
        ".production-graphics", ".production-replay", ".production-screens",
        ".broadcast-destinations",
    ):
        assert mapping.count(f'"{selector}"') == 1


def test_broadcast_tabs_only_change_presentation_and_are_persistent() -> None:
    section = JS[JS.index("function setBroadcastWorkspaceView") : JS.index("function readinessPanel")]
    assert "panel.hidden=panel.dataset.broadcastPanel!==view" in section
    assert 'localStorage.setItem(BROADCAST_WORKSPACE_VIEW_KEY,view)' in section
    assert 'localStorage.getItem(BROADCAST_WORKSPACE_VIEW_KEY)||"live"' in section
    assert "ArrowLeft" in section and "ArrowRight" in section and "Home" in section and "End" in section
    assert "setInterval" not in section
    assert "fetch(" not in section
    assert "api(" not in section


def test_broadcast_console_is_compact_sticky_and_responsive() -> None:
    assert '.workspace[data-workspace="broadcast"].active{' in CSS
    assert "grid-template-columns:repeat(12,minmax(0,1fr))!important" in CSS
    assert ".broadcast-workspace-tabs{" in CSS
    assert "position:sticky!important" in CSS
    assert "order:-100!important" in CSS
    assert "grid-template-columns:repeat(7,minmax(104px,1fr))!important" in CSS
    assert "overflow-x:auto!important" in CSS
    assert 'html[data-theme="light"] body.studiox-ui4 .broadcast-workspace-tabs' in CSS


def test_live_control_adapts_its_hierarchy_to_session_state() -> None:
    assert 'workspace.dataset.productionSession=active?"live":"idle"' in JS
    assert '>.production-session-metadata{order:-85!important}' in CSS
    assert '>.production-session{order:-80!important}' in CSS
    assert '>.show-preflight{order:-80!important}' in CSS
    assert '>.production-switcher-shell{order:-60!important}' in CSS
    assert '[data-production-session="live"]>.production-session{order:-80!important;grid-column:1/-1!important}' in CSS
    assert '[data-production-session="live"]>.production-switcher-shell{order:-70!important}' in CSS
