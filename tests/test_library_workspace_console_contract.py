from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
STYLES = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_library_has_six_real_accessible_views():
    assert 'id="libraryWorkspaceTabs" role="tablist" aria-label="Reference Library views"' in CONTROL
    for view, panel in (
        ("overview", "libraryOverview"),
        ("metadata", "libraryMetadata"),
        ("artwork", "libraryArtwork"),
        ("indexes", "libraryIndexes"),
        ("providers", "libraryProviders"),
        ("updates", "libraryUpdates"),
    ):
        assert f'data-library-view="{view}"' in CONTROL
        assert f'aria-controls="{panel}"' in CONTROL
        assert f'id="{panel}" role="tabpanel"' in CONTROL


def test_library_console_reads_existing_status_endpoints_without_polling():
    for endpoint in (
        "/api/master-builder/status",
        "/api/assets/status",
        "/api/intelligence/status",
        "/api/artwork-index/status",
        "/api/index-activation/status",
        "/api/providers/status",
        "/api/jobs/status",
        "/api/boot/status",
        "/api/system/health",
    ):
        assert f'api("{endpoint}")' in SCRIPT
    loader = SCRIPT[SCRIPT.index("async function loadLibraryConsole"):SCRIPT.index("function initializeLibraryConsole")]
    assert 'method:"POST"' not in loader
    assert "setInterval" not in loader


def test_library_preserves_explicit_existing_maintenance_actions():
    for endpoint in (
        "/api/library/optimize",
        "/api/index/incremental",
        "/api/providers/check",
        "/api/assets/scan",
        "/api/master-builder/refresh",
    ):
        assert endpoint in CONTROL
    assert "async function maintenance(path,label,button=null)" in SCRIPT
    assert 'api(path,{method:"POST",body:"{}"})' in SCRIPT


def test_library_maintenance_actions_have_visible_feedback_and_click_protection():
    assert "async function maintenance(path,label,button=null)" in SCRIPT
    assert "if(button){button.disabled=true" in SCRIPT
    assert "notify(result.ok===false?`${label} Failed`:`${label} Queued`" in SCRIPT
    assert "loadLibraryConsole().catch(()=>{})" in SCRIPT
    assert "finally{if(button){button.disabled=false;button.textContent=originalLabel;}}" in SCRIPT
    assert CONTROL.count(",this)\"") == 5


def test_library_update_metric_describes_imported_records_truthfully():
    assert "Records Added" in CONTROL
    assert "New Releases</span>" not in CONTROL
    assert "builder.new_releases_added" in SCRIPT


def test_library_navigation_is_persistent_and_keyboard_accessible():
    assert 'const LIBRARY_VIEW_KEY="rareiq.library.view.v1"' in SCRIPT
    assert "function setLibraryView" in SCRIPT
    assert "function initializeLibraryConsole" in SCRIPT
    assert "initializeLibraryConsole();" in SCRIPT
    assert "localStorage.setItem(LIBRARY_VIEW_KEY,view)" in SCRIPT
    for key in ("ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End"):
        assert f'"{key}"' in SCRIPT


def test_library_console_reports_real_status_without_exposing_secrets():
    for element_id in (
        "libraryOverviewSets",
        "libraryMetadataCurrent",
        "libraryArtworkAssets",
        "libraryIndexGlobalRecords",
        "libraryProviderRows",
        "libraryUpdateVersion",
    ):
        assert f'id="{element_id}"' in CONTROL
    render = SCRIPT[SCRIPT.index("function renderLibraryConsole"):SCRIPT.index("async function loadLibraryConsole")]
    assert ".secrets" not in render
    assert "provider_health" in render


def test_library_console_is_responsive_and_focus_safe():
    assert '.library-console-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr))' in STYLES
    assert '@media(max-width:1200px){.workspace[data-workspace="library"] .library-console-metrics{grid-template-columns:repeat(2,minmax(0,1fr))' in STYLES
    assert '@media(max-width:540px){.workspace[data-workspace="library"] .library-console-metrics{grid-template-columns:1fr}' in STYLES
    assert '.workspace[data-workspace="library"] [role="tabpanel"]:focus-visible' in STYLES


def test_library_loads_only_when_opened_or_refreshed():
    assert 'if(name==="library") loadLibraryConsole()' in SCRIPT
    assert '$("libraryConsoleRefresh")?.addEventListener("click",()=>loadLibraryConsole()' in SCRIPT
