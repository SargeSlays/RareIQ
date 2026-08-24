from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx


class SpotifyService:
    API = "https://api.spotify.com/v1"
    ACCOUNTS = "https://accounts.spotify.com"
    SCOPES = "user-read-playback-state user-modify-playback-state user-read-currently-playing playlist-read-private playlist-read-collaborative user-read-playback-position"

    def __init__(self, settings_path: Path | None = None) -> None:
        self.settings_path = settings_path or (Path(__file__).resolve().parents[2] / "spotify_settings.json")
        saved = self._load_settings()
        self.client_id = os.getenv("SPOTIFY_CLIENT_ID", str(saved.get("client_id", ""))).strip()
        self.redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI", str(saved.get("redirect_uri", "http://127.0.0.1:8765/api/spotify/callback"))).strip()
        self._verifiers: dict[str, str] = {}
        self._token: dict[str, Any] = {}

    def _load_settings(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.settings_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def configure(self, client_id: str, redirect_uri: str | None = None) -> dict[str, Any]:
        client_id = str(client_id or "").strip()
        redirect_uri = str(redirect_uri or self.redirect_uri).strip()
        if client_id and not 16 <= len(client_id) <= 128:
            raise ValueError("spotify_client_id_invalid")
        if not redirect_uri.startswith("http://127.0.0.1:") or not redirect_uri.endswith("/api/spotify/callback"):
            raise ValueError("spotify_redirect_uri_must_use_rareiq_loopback_callback")
        if client_id != self.client_id:
            self._token = {}
            self._verifiers = {}
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(json.dumps({"client_id": client_id, "redirect_uri": redirect_uri}, indent=2), encoding="utf-8")
        return self.setup()

    def setup(self) -> dict[str, Any]:
        return {"configured": self.configured, "client_id": self.client_id, "redirect_uri": self.redirect_uri, "developer_dashboard_url": "https://developer.spotify.com/dashboard"}

    @property
    def configured(self) -> bool:
        return bool(self.client_id)

    def begin_auth(self) -> str:
        if not self.configured:
            raise ValueError("spotify_not_configured")
        state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        self._verifiers[state] = verifier
        return f"{self.ACCOUNTS}/authorize?{urlencode({'client_id': self.client_id, 'response_type': 'code', 'redirect_uri': self.redirect_uri, 'scope': self.SCOPES, 'state': state, 'code_challenge_method': 'S256', 'code_challenge': challenge})}"

    async def finish_auth(self, code: str, state: str) -> None:
        verifier = self._verifiers.pop(state, "")
        if not verifier:
            raise ValueError("spotify_auth_state_invalid")
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(f"{self.ACCOUNTS}/api/token", data={"client_id": self.client_id, "grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri, "code_verifier": verifier})
            response.raise_for_status()
            self._set_token(response.json())

    def _set_token(self, token: dict[str, Any]) -> None:
        refresh = token.get("refresh_token") or self._token.get("refresh_token")
        self._token = dict(token) | {"refresh_token": refresh, "expires_at": time.time() + int(token.get("expires_in", 3600)) - 30}

    async def _access_token(self) -> str:
        if not self._token.get("access_token"):
            raise ValueError("spotify_not_connected")
        if time.time() >= float(self._token.get("expires_at", 0)):
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(f"{self.ACCOUNTS}/api/token", data={"client_id": self.client_id, "grant_type": "refresh_token", "refresh_token": self._token.get("refresh_token")})
                response.raise_for_status()
                self._set_token(response.json())
        return str(self._token["access_token"])

    async def request(self, method: str, path: str, *, params: dict[str, Any] | None = None, json: Any = None) -> Any:
        token = await self._access_token()
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.request(method, f"{self.API}{path}", params=params, json=json, headers={"Authorization": f"Bearer {token}"})
            if response.status_code == 204:
                return None
            response.raise_for_status()
            return response.json()

    async def status(self) -> dict[str, Any]:
        if not self.configured:
            return {**self.setup(), "connected": False}
        if not self._token:
            return {**self.setup(), "connected": False}
        profile = await self.request("GET", "/me")
        playback = await self.request("GET", "/me/player")
        devices = await self.request("GET", "/me/player/devices")
        queue = await self.request("GET", "/me/player/queue")
        return {**self.setup(), "connected": True, "profile": profile, "playback": playback, "devices": devices.get("devices", []), "queue": (queue or {}).get("queue", [])[:20]}


spotify = SpotifyService()
