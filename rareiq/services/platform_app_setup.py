"""Explicit local app configuration; no provider sign-in or network operations."""
from __future__ import annotations

import os
import re


class AppSetupError(ValueError):
    pass


def validate_configuration(platform, value):
    if platform not in {"youtube", "kick"}:
        raise AppSetupError("invalid_app_provider")
    if not isinstance(value, dict) or set(value) != {"client_id", "client_secret"}:
        raise AppSetupError("invalid_app_configuration")
    client, secret = value["client_id"], value["client_secret"]
    pattern = r"[A-Za-z0-9_-]{1,220}\.apps\.googleusercontent\.com" if platform == "youtube" else r"[A-Za-z0-9_-]{1,160}"
    if (not isinstance(client, str) or not re.fullmatch(pattern, client)
            or not isinstance(secret, str) or not 1 <= len(secret) <= 4096
            or any(not 33 <= ord(c) <= 126 for c in secret)):
        raise AppSetupError("invalid_app_configuration")
    return {"client_id": client, "client_secret": secret}


class PlatformAppSetupService:
    def __init__(self, vault, services, *, environment=None):
        self._vault, self._services = vault, dict(services)
        self._environment = os.environ if environment is None else environment

    async def configure(self, platform, value):
        config = validate_configuration(platform, value)
        service = self._services.get(platform)
        if service is None or self._vault is None:
            raise AppSetupError("app_setup_unavailable")
        async with service._credential_lock:
            if service._closed:
                raise AppSetupError("app_setup_unavailable")
            supplied = {key: self._environment.get("RAREIQ_" + platform.upper() + "_" + key.upper(), "").strip()
                        for key in ("client_id", "client_secret")}
            if any(supplied.values()) and supplied != config:
                raise AppSetupError("external_app_configuration_active")
            try:
                stored = self._vault.get(platform) or {}
                if not isinstance(stored, dict):
                    raise ValueError()
                if all(stored.get(key) == item for key, item in config.items()):
                    return {"configured": True, "replayed": True, "platform": platform}
                auth_fields = ("access_token", "refresh_token", "token_type", "channel_id", "channel_name", "channel_login",
                               "channel_slug", "public_label", "scopes", "expires_at")
                if service._pending is not None or any(stored.get(key) for key in auth_fields):
                    raise AppSetupError("disconnect_before_app_setup")
                self._vault.set(platform, config)
            except AppSetupError:
                raise
            except Exception:
                raise AppSetupError("account_storage_unavailable") from None
            # No await between the final record check, write and invalidation.
            # A Begin waiting on listener startup must retire its old configuration.
            service._generation += 1
            service._reason = "authorization_required"
            return {"configured": True, "replayed": False, "platform": platform}
