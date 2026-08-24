from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
STYLES = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_settings_has_five_accurate_accessible_views():
    assert 'id="settingsWorkspaceTabs" role="tablist" aria-label="Studio X settings views"' in CONTROL
    for view, label, panel in (
        ("appearance", "Appearance", "settingsAppearance"),
        ("mobile", "Mobile Access", "settingsMobile"),
        ("recognition", "Recognition", "settingsRecognition"),
        ("health", "System Health", "settingsHealth"),
        ("interfaces", "Interfaces", "settingsInterfaces"),
    ):
        assert f'data-settings-view="{view}"' in CONTROL
        assert f'>{label}</button>' in CONTROL
        assert f'aria-controls="{panel}"' in CONTROL
        assert f'id="{panel}" role="tabpanel"' in CONTROL


def test_settings_default_and_panel_visibility_contract():
    assert 'id="settingsTabAppearance" type="button" role="tab" data-settings-view="appearance" aria-selected="true"' in CONTROL
    assert 'id="settingsAppearance" role="tabpanel"' in CONTROL
    for panel in ("settingsMobile", "settingsRecognition", "settingsHealth", "settingsInterfaces"):
        panel_source = CONTROL[CONTROL.index(f'id="{panel}"') : CONTROL.index(f'id="{panel}"') + 180]
        assert "hidden" in panel_source
    assert '.workspace[data-workspace="settings"] .settings-panel[hidden]{display:none!important}' in STYLES


def test_settings_navigation_is_persistent_and_keyboard_accessible():
    assert 'const SETTINGS_VIEW_KEY="rareiq.settings.view.v1"' in SCRIPT
    assert "function setSettingsView" in SCRIPT
    assert "function initializeSettingsConsole" in SCRIPT
    assert "initializeSettingsConsole();" in SCRIPT
    assert "localStorage.setItem(SETTINGS_VIEW_KEY,view)" in SCRIPT
    for key in ("ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End"):
        assert f'"{key}"' in SCRIPT
    assert '.workspace[data-workspace="settings"] [role="tabpanel"]:focus-visible' in STYLES


def test_existing_settings_controls_and_interface_handlers_are_preserved():
    for element_id in (
        "mobileAccessRefresh",
        "mobileAccessCopy",
        "mobileWakeLockEnabled",
        "automaticCardRemovalEnabled",
        "automaticCardRemovalSensitivity",
        "systemHealthGrid",
        "cameraManagerState",
    ):
        assert f'id="{element_id}"' in CONTROL
    assert 'data-theme-choice="dark"' in CONTROL
    assert 'onclick="openProgram()"' in CONTROL
    assert "window.open('/studio501')" in CONTROL
    assert "window.open('/legacy-control')" in CONTROL


def test_settings_navigation_does_not_add_api_calls_or_polling():
    navigation = SCRIPT[SCRIPT.index("const SETTINGS_VIEW_KEY") : SCRIPT.index("function setBroadcastWorkspaceView")]
    assert "api(" not in navigation
    assert "fetch(" not in navigation
    assert "setInterval" not in navigation
    assert "setTimeout" not in navigation
