from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
from dataclasses import dataclass
from typing import Any, Mapping


REMOTE_ACCESS_COOKIE = "rareiq_remote_session"
MIN_REMOTE_TOKEN_CHARS = 24
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
REMOTE_BIND_HOSTS = {"0.0.0.0", "::"}


class RemoteAccessConfigurationError(RuntimeError):
    pass


def _enabled(value: Any) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def is_loopback_client(host: str | None) -> bool:
    value = str(host or "").strip().casefold()
    if value in LOOPBACK_HOSTS:
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class RemoteAccessPolicy:
    enabled: bool
    session_id: str
    _token: str

    @classmethod
    def from_environment(
        cls,
        session_id: str,
        *,
        environment: Mapping[str, str] | None = None,
        secret_store: Any | None = None,
    ) -> "RemoteAccessPolicy":
        environment = environment or os.environ
        enabled = _enabled(environment.get("RAREIQ_REMOTE_ACCESS"))
        token = str(environment.get("RAREIQ_REMOTE_ACCESS_TOKEN") or "").strip()
        if not token and secret_store is not None:
            token = str(secret_store.get("remote_access_token") or "").strip()
        if enabled and len(token) < MIN_REMOTE_TOKEN_CHARS:
            raise RemoteAccessConfigurationError(
                f"Remote access requires a token of at least {MIN_REMOTE_TOKEN_CHARS} characters."
            )
        return cls(enabled=enabled, session_id=str(session_id), _token=token)

    @property
    def cookie_value(self) -> str:
        if not self.enabled:
            return ""
        return hmac.new(
            self._token.encode("utf-8"),
            self.session_id.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def verify_pairing_token(self, candidate: str | None) -> bool:
        if not self.enabled:
            return False
        return hmac.compare_digest(
            self._token.encode("utf-8"),
            str(candidate or "").encode("utf-8"),
        )

    def authorizes(self, client_host: str | None, cookie_value: str | None) -> bool:
        if is_loopback_client(client_host):
            return True
        if not self.enabled:
            return False
        return bool(cookie_value) and hmac.compare_digest(
            self.cookie_value,
            str(cookie_value),
        )


def validate_server_binding(host: str, policy: RemoteAccessPolicy) -> str:
    normalized = str(host or "").strip().casefold()
    if normalized in LOOPBACK_HOSTS:
        return normalized
    if normalized in REMOTE_BIND_HOSTS and policy.enabled:
        return normalized
    if normalized in REMOTE_BIND_HOSTS:
        raise RemoteAccessConfigurationError(
            "LAN binding requires explicit authenticated remote access."
        )
    raise RemoteAccessConfigurationError(
        "RareIQ permits only loopback or authenticated wildcard LAN bindings."
    )
