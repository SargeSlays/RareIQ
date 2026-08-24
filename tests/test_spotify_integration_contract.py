from pathlib import Path

SERVER = Path("rareiq/web/server.py").read_text(encoding="utf-8")
SERVICE = Path("rareiq/services/spotify_service.py").read_text(encoding="utf-8")
CONTROL = Path("rareiq/web/static/control.html").read_text(encoding="utf-8")
STUDIO = Path("rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = Path("rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


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
    assert '.spotify-workspace' in CSS
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
