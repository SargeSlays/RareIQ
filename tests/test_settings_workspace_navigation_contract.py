from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
STYLES = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
DECK = (ROOT / "rareiq/web/static/studiox_command_deck.css").read_text(encoding="utf-8")


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
    assert '.workspace[data-workspace="settings"] .settings-panel[hidden]' in DECK


def test_settings_navigation_is_persistent_and_keyboard_accessible():
    assert 'const SETTINGS_VIEW_KEY="rareiq.settings.view.v1"' in SCRIPT
    assert "function setSettingsView" in SCRIPT
    assert "function initializeSettingsConsole" in SCRIPT
    assert "initializeSettingsConsole();" in SCRIPT
    assert "localStorage.setItem(SETTINGS_VIEW_KEY,view)" in SCRIPT
    for key in ("ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End"):
        assert f'"{key}"' in SCRIPT
    assert '.workspace[data-workspace="settings"] [role="tabpanel"]:focus-visible' in DECK


def test_settings_command_deck_owns_navigation_and_panel_visuals():
    settings = DECK[DECK.index("/* Settings */") : DECK.index("/* Desktop app workspaces")]
    assert '[data-settings-view][aria-selected="true"]' in settings
    assert ".mobile-access-settings" in settings
    assert ".health-grid" in settings
    assert ".settings-interface-panel > .grid" in settings
    assert '.workspace[data-workspace="settings"] .settings-panel[hidden]{display:none!important}' not in STYLES
    assert '[data-settings-view][aria-selected="true"]' not in STYLES


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


def test_system_health_updates_only_the_settings_health_grid():
    health = SCRIPT[SCRIPT.index("async function loadSystemHealth") : SCRIPT.index("let serverConnectionState")]
    assert 'const grid=$("systemHealthGrid")' in health
    assert 'grid.querySelector(`[data-health="${name}"]`)' in health
    assert 'document.querySelector(`[data-health="${name}"]`)' not in health
    assert 'card.dataset.state=componentState' in health
    assert 'card.dataset.state="unavailable"' in health


def test_settings_command_deck_removes_legacy_toggle_gradients_and_maps_health_states():
    semantic = DECK[DECK.index("/* Settings semantic cleanup */") : DECK.index("/* Desktop app workspaces")]
    assert ".card-handoff-toggle input:checked + i" in semantic
    assert "background: var(--sx-accent-strong)" in semantic
    assert '.health-card[data-state="warning"]' in semantic
    assert "var(--sx-warning)" in semantic
    assert "var(--sx-danger)" in semantic
    assert "#735ce8" not in semantic.lower()


def test_settings_uses_compact_operator_surfaces_at_desktop_widths():
    semantic = DECK[DECK.index("/* Settings semantic cleanup */") : DECK.index("/* Desktop app workspaces")]
    assert "grid-template-columns: repeat(5, minmax(0, 1fr)) !important;" in semantic
    assert ":is(.card-handoff-toggle, .card-handoff-sound, .mobile-wake-lock)" in semantic
    assert "grid-template-columns: minmax(260px, .75fr) minmax(480px, 1.25fr) !important;" in DECK
    assert "max-width: 720px !important;" in DECK
    assert ".settings-interface-panel .card" in semantic
    assert "border-left: 3px solid var(--sx-accent-strong) !important;" in semantic


def test_settings_boot_copy_has_no_legacy_encoding_artifacts():
    assert "Camera Manager booting…" in CONTROL
    assert "Ã" not in CONTROL[CONTROL.index('id="settingsHealth"') : CONTROL.index('id="settingsInterfaces"')]
