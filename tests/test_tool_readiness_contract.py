from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "rareiq" / "web" / "static" / "studiox.js").read_text(encoding="utf-8-sig")
CSS = (ROOT / "rareiq" / "web" / "static" / "studiox_update15.css").read_text(encoding="utf-8-sig")


def test_api_requests_are_timeout_retry_and_abort_safe() -> None:
    assert "timeoutMs=15000" in SCRIPT
    assert "new AbortController()" in SCRIPT
    assert "navigator.onLine===false" in SCRIPT
    assert '"rareiq:api-error"' in SCRIPT


def test_each_tool_workspace_has_runtime_readiness() -> None:
    for workspace in ("collection", "broadcast", "creator", "soundboard", "spotify", "ai-lab", "library", "settings"):
        assert f'{workspace}:' in SCRIPT or f'"{workspace}":' in SCRIPT
    assert 'name==="voice-mod"' in SCRIPT
    assert 'name==="camera-fx"' in SCRIPT
    assert "refreshWorkspaceReadiness(name)" in SCRIPT
    assert "initializeWorkspaceReadiness()" in SCRIPT


def test_readiness_ui_is_responsive_and_accessible() -> None:
    assert 'panel.setAttribute("role","status")' in SCRIPT
    assert 'panel.setAttribute("aria-live","polite")' in SCRIPT
    assert ".workspace-readiness" in CSS
    assert "prefers-reduced-motion:reduce" in CSS
