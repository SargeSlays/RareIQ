from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")
CONTROL = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
OVERLAY = (ROOT / "rareiq/web/static/overlay_pokedex.html").read_text(encoding="utf-8")


def test_rare_intelligence_theme_api_is_persistent_and_validated():
    assert "class RareIntelligenceThemeRequest(BaseModel)" in SERVER
    assert '@app.get("/api/rare-intelligence/theme")' in SERVER
    assert '@app.post("/api/rare-intelligence/theme")' in SERVER
    assert '"rare_intelligence_theme": theme' in SERVER
    assert '"theme": theme' in SERVER


def test_control_exposes_browser_source_designer():
    for control_id in (
        "rareIntelligenceCustomize",
        "rareIntelligenceThemeEditor",
        "rareIntelligenceThemePreview",
        "riThemeAccent",
        "riThemeBackground",
        "riThemeOpacity",
        "riThemeAlignment",
        "riThemeSave",
    ):
        assert f'id="{control_id}"' in CONTROL
    assert 'api("/api/overlay/state"' in SCRIPT
    assert "rare-intelligence-theme-preview" in SCRIPT
    assert "RARE_INTELLIGENCE_THEME_PRESETS" in SCRIPT
    assert 'minimal:{preset:"minimal"' in SCRIPT
    assert 'broadcast:{preset:"broadcast"' in SCRIPT
    assert '$("riThemePreset")?.addEventListener("change"' in SCRIPT


def test_overlay_applies_theme_and_supports_safe_preview():
    assert 'new URLSearchParams(location.search).get("preview")==="1"' in OVERLAY
    assert "function applyTheme(theme={})" in OVERLAY
    assert "--ri-accent" in OVERLAY
    assert 'stage.dataset.align=theme.alignment||"left"' in OVERLAY
    assert 'theme[`show_${key}`]' in OVERLAY
    assert 'document.body.classList.toggle("preview",preview)' in OVERLAY
    assert 'studiox-ri-theme-preview-shell' in CONTROL
    assert 'if(!pokemon){' in OVERLAY
    assert 'byId("art").removeAttribute("src")' in OVERLAY
