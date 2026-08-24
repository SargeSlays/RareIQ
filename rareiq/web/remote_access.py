from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Mapping


REMOTE_ACCESS_COOKIE = "rareiq_remote_session"
MIN_REMOTE_TOKEN_CHARS = 24
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
REMOTE_BIND_HOSTS = {"0.0.0.0", "::"}
PAIRING_ATTEMPT_LIMIT = 5
PAIRING_ATTEMPT_WINDOW_SECONDS = 60.0
PAIRING_LOCKOUT_SECONDS = 300.0
PAIRING_CLIENT_CAPACITY = 512


class RemoteAccessConfigurationError(RuntimeError):
    pass


class PairingAttemptLimiter:
    def __init__(
        self,
        *,
        attempt_limit: int = PAIRING_ATTEMPT_LIMIT,
        window_seconds: float = PAIRING_ATTEMPT_WINDOW_SECONDS,
        lockout_seconds: float = PAIRING_LOCKOUT_SECONDS,
        capacity: int = PAIRING_CLIENT_CAPACITY,
    ) -> None:
        self.attempt_limit = max(1, int(attempt_limit))
        self.window_seconds = max(1.0, float(window_seconds))
        self.lockout_seconds = max(1.0, float(lockout_seconds))
        self.capacity = max(1, int(capacity))
        self._lock = threading.RLock()
        self._clients: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _key(client_host: str | None) -> str:
        return str(client_host or "unknown").strip().casefold() or "unknown"

    def retry_after(self, client_host: str | None, *, now: float | None = None) -> int:
        current = time.monotonic() if now is None else float(now)
        key = self._key(client_host)
        with self._lock:
            state = self._clients.get(key)
            if not state:
                return 0
            blocked_until = float(state.get("blocked_until") or 0.0)
            if blocked_until > current:
                return max(1, int(blocked_until - current + 0.999))
            if blocked_until:
                self._clients.pop(key, None)
                return 0
            attempts = [
                value
                for value in state.get("attempts") or []
                if current - float(value) <= self.window_seconds
            ]
            if attempts:
                state["attempts"] = attempts
                state["last_seen"] = current
            else:
                self._clients.pop(key, None)
            return 0

    def record_failure(self, client_host: str | None, *, now: float | None = None) -> int:
        current = time.monotonic() if now is None else float(now)
        key = self._key(client_host)
        with self._lock:
            self._prune(current)
            state = self._clients.setdefault(
                key,
                {"attempts": [], "blocked_until": 0.0, "last_seen": current},
            )
            attempts = [
                value
                for value in state.get("attempts") or []
                if current - float(value) <= self.window_seconds
            ]
            attempts.append(current)
            state.update({"attempts": attempts, "last_seen": current})
            if len(attempts) >= self.attempt_limit:
                state["blocked_until"] = current + self.lockout_seconds
                return int(self.lockout_seconds)
            return 0

    def clear(self, client_host: str | None) -> None:
        with self._lock:
            self._clients.pop(self._key(client_host), None)

    def _prune(self, current: float) -> None:
        expired = [
            key
            for key, state in self._clients.items()
            if current - float(state.get("last_seen") or 0.0)
            > self.window_seconds + self.lockout_seconds
        ]
        for key in expired:
            self._clients.pop(key, None)
        if len(self._clients) < self.capacity:
            return
        oldest = min(
            self._clients,
            key=lambda key: float(self._clients[key].get("last_seen") or 0.0),
        )
        self._clients.pop(oldest, None)


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
