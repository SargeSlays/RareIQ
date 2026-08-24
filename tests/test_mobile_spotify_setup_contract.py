from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "rareiq" / "web" / "static"
HTML = (STATIC / "control.html").read_text(encoding="utf-8-sig")
JS = (STATIC / "studiox.js").read_text(encoding="utf-8-sig")
CSS = (STATIC / "studiox_update15.css").read_text(encoding="utf-8-sig")


def test_spotify_redirect_uri_is_a_readable_copy_safe_field() -> None:
    assert HTML.count('<textarea id="spotifyRedirectUri"') == 1
    assert 'rows="2" readonly spellcheck="false"' in HTML
    assert 'aria-label="Spotify redirect URI"' in HTML
    assert "http://127.0.0.1:8765/api/spotify/callback" in HTML
    assert "white-space:pre-wrap" in CSS
    assert "overflow-wrap:anywhere" in CSS
    assert "word-break:break-all" in CSS


def test_spotify_redirect_copy_and_setup_handlers_are_unchanged() -> None:
    assert HTML.count('id="spotifyCopyRedirect"') == 1
    assert HTML.count('id="spotifySaveSetup"') == 1
    assert 'navigator.clipboard.writeText($("spotifyRedirectUri")?.value||"")' in JS
    assert 'redirectUri=$("spotifyRedirectUri")?.value?.trim()||""' in JS


def test_spotify_setup_uses_the_current_rareiq_port_until_configured() -> None:
    assert "function spotifyRuntimeRedirectUri" in JS
    assert 'const port=window.location.port||"8765"' in JS
    assert '`http://127.0.0.1:${port}/api/spotify/callback`' in JS
    assert 'payload.configured===true&&saved' in JS


def test_spotify_redirect_and_copy_button_share_a_narrow_safe_grid() -> None:
    assert "grid-template-columns:minmax(0,1fr) auto" in CSS
    assert "body.studiox-ui4 .spotify-setup-card textarea" in CSS
    assert "min-height:52px" in CSS
