from pathlib import Path

import pytest

from rareiq.services.spotify_service import SpotifyService


def test_spotify_setup_persists_public_pkce_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_REDIRECT_URI", raising=False)
    path = tmp_path / "spotify.json"
    service = SpotifyService(path)
    assert service.setup()["configured"] is False
    configured = service.configure("1234567890abcdef", "http://127.0.0.1:8765/api/spotify/callback")
    assert configured["configured"] is True
    assert configured["client_id"] == "1234567890abcdef"
    assert SpotifyService(path).client_id == "1234567890abcdef"


def test_spotify_setup_rejects_non_rareiq_redirect(tmp_path: Path) -> None:
    service = SpotifyService(tmp_path / "spotify.json")
    with pytest.raises(ValueError, match="loopback"):
        service.configure("1234567890abcdef", "http://localhost:8765/api/spotify/callback")
