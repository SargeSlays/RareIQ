from pathlib import Path

SERVER = Path("rareiq/web/server.py").read_text(encoding="utf-8")
SERVICE = Path("rareiq/services/spotify_service.py").read_text(encoding="utf-8")
CONTROL = Path("rareiq/web/static/control.html").read_text(encoding="utf-8")
STUDIO = Path("rareiq/web/static/studiox.js").read_text(encoding="utf-8")
LEGACY_CSS = Path("rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
CSS = Path("rareiq/web/static/studiox_command_deck.css").read_text(encoding="utf-8")


def test_spotify_uses_pkce_oauth_and_local_token_state():
    assert 'SPOTIFY_CLIENT_ID' in SERVICE
    assert 'code_challenge_method' in SERVICE
    assert 'S256' in SERVICE
    assert 'client_secret' not in SERVICE
    assert 'refresh_token' in SERVICE


def test_spotify_api_supports_status_search_playlists_and_player_commands():
    assert '@app.get("/api/spotify/status")' in SERVER
    assert '@app.get("/api/spotify/connect")' in SERVER
    assert '@app.get("/api/spotify/callback")' in SERVER
    assert '@app.get("/api/spotify/search")' in SERVER
    assert '@app.get("/api/spotify/playlists")' in SERVER
    assert '@app.post("/api/spotify/player")' in SERVER
    assert '@app.get("/api/spotify/setup")' in SERVER
    assert '@app.post("/api/spotify/setup")' in SERVER
    for action in ('"play"', '"pause"', '"next"', '"previous"', '"queue"', '"seek"', '"volume"', '"transfer"'):
        assert action in SERVER


def test_spotify_has_left_rail_app_and_right_tool():
    assert 'data-target="spotify"' in CONTROL
    assert 'data-workspace="spotify"' in CONTROL
    assert 'data-studiox-widget="spotify"' in CONTROL
    assert 'id="spotifySearchForm"' in CONTROL
    assert 'id="spotifyDevice"' in CONTROL
    assert 'id="spotifyToolPlay"' in CONTROL
    assert 'function loadSpotify()' in STUDIO
    assert 'function spotifyCommand' in STUDIO
    assert '.workspace[data-workspace="spotify"]' in CSS
    assert '.spotify-mini-player' in CSS
    assert 'id="spotifySetupCard"' in CONTROL
    assert 'id="spotifyClientId"' in CONTROL
    assert "function startSpotifyConnection" in STUDIO
    assert "function saveSpotifySetup" in STUDIO


def test_spotify_dj_refinements_include_queue_modes_and_soundboard_ducking():
    assert 'id="spotifyQueue"' in CONTROL
    assert 'id="spotifyShuffle"' in CONTROL
    assert 'id="spotifyRepeat"' in CONTROL
    assert 'id="spotifyDuckEnabled"' in CONTROL
    assert 'id="spotifyAppDuckEnabled"' in CONTROL
    assert '"/me/player/queue"' in SERVICE
    assert 'action == "shuffle"' in SERVER
    assert 'action == "repeat"' in SERVER
    assert "function renderSpotifyEnhancements" in STUDIO
    assert "function setSpotifyDucking" in STUDIO
    assert 'setInterval(()=>{if(document.hidden!==true)loadSpotify()' in STUDIO
    assert 'spotifyDuckedVolume' in STUDIO
    assert '.spotify-queue-section' in CSS
    assert '.spotify-duck-control' in CSS


def test_spotify_disconnected_state_disables_commands_without_blocking_setup():
    assert "function setSpotifyAvailability" in STUDIO
    for control_id in (
        "spotifyShuffle",
        "spotifyPrevious",
        "spotifyPlay",
        "spotifyNext",
        "spotifyRepeat",
        "spotifyDevice",
        "spotifyVolume",
        "spotifySearch",
        "spotifyRefresh",
        "spotifyToolPrevious",
        "spotifyToolPlay",
        "spotifyToolNext",
    ):
        assert f'"{control_id}"' in STUDIO
    assert 'searchButton.disabled=!connected' in STUDIO
    assert 'Complete the one-time setup above to connect Spotify.' in STUDIO
    assert '.spotify-shell, .spotify-mini-player) :is(button, input, select):disabled' in CSS


def test_spotify_connection_state_and_background_polling_are_truthful():
    assert 'payload.configured?"Authorize Spotify":"Set Up Spotify"' in STUDIO
    assert "if(!payload.connected&&spotifyRefreshTimer)" in STUDIO
    assert "clearInterval(spotifyRefreshTimer)" in STUDIO
    assert "spotifyRefreshTimer=0" in STUDIO


def test_spotify_search_and_ducking_have_safe_operator_fallbacks():
    assert 'const term=String(query||"").trim()' in STUDIO
    assert "Enter a track, artist, or playlist to search." in STUDIO
    assert "No Spotify results found for" in STUDIO
    assert "No Spotify playlists are available for this account." in STUDIO
    assert "if(!active&&spotifyDuckedVolume!==null)" in STUDIO
    assert 'spotifyCommand("volume",{volume_percent:restore})' in STUDIO


def test_spotify_presentation_has_one_semantic_owner():
    assert "/* Spotify */" in CSS
    assert 'body.studiox-command-deck[data-studiox-visual-system="unified"] .workspace[data-workspace="spotify"]' in CSS
    assert "background: var(--sx-surface-raised) !important" in CSS
    assert "border: 1px solid var(--sx-divider) !important" in CSS
    assert "scrollbar-color: var(--sx-divider-strong) var(--sx-chrome) !important" in CSS
    assert "/* Spotify DJ app and compact right-side remote. */" not in LEGACY_CSS
    assert "/* Spotify DJ refinements. */" not in LEGACY_CSS
    assert "body.studiox-ui4 .spotify-setup-card{" not in LEGACY_CSS


def test_spotify_command_deck_prioritizes_player_and_live_queue():
    assert "grid-template-columns: minmax(230px, .52fr) minmax(0, 1.48fr)" in CSS
    assert "grid-template-columns: minmax(0, .94fr) minmax(0, .94fr) minmax(0, 1.12fr)" in CSS
    assert ".workspace[data-workspace=\"spotify\"] .spotify-queue-section" in CSS
    assert "#spotifyQueueCount" in CSS
    assert "#spotifyPlay" in CSS
    assert "min-height: 292px" in CSS


def test_spotify_focus_and_responsive_setup_remain_operator_safe():
    assert ':is(button, a, input, select, textarea):focus-visible' in CSS
    assert ".spotify-setup-card ol" in CSS
    assert "grid-column: auto !important" in CSS
    assert "border-left: 0 !important" in CSS
