"""Private, per-profile platform credentials. No account/network side effects.

The caller supplies an absolute JSON file outside source (normally its F: profile).
Public status describes stored fields only, never a verified account or connection.
All cooperating writers in this process share a lock; there is no cross-process CAS.
"""
from __future__ import annotations

import base64
import ctypes
import json
import math
import os
from pathlib import Path
import threading
from uuid import uuid4

from rareiq.core.runtime_paths import _resolved


PROVIDERS = ("twitch", "youtube", "kick")
MAX_FILE_BYTES = 256 * 1024
MAX_RECORD_BYTES = 48 * 1024
MAX_CIPHER_BYTES = 64 * 1024
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()
_STRINGS = {"public_label": 80, "client_id": 512, "client_secret": 4096,
            "access_token": 16384, "refresh_token": 16384, "token_type": 32}
_CHANNELS = {"twitch": {"channel_id": 128, "channel_login": 64},
             "youtube": {"channel_id": 128, "channel_name": 128},
             "kick": {"channel_id": 128, "channel_slug": 128}}


class PlatformCredentialsError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _fail(code):
    raise PlatformCredentialsError(code)


def _windows_available():
    return os.name == "nt"


class WindowsUserCipher:
    """Current Windows user's DPAPI; machine-wide protection is never requested."""
    @property
    def available(self):
        return _windows_available()

    def _crypt(self, value, *, decrypt=False):
        if not self.available:
            _fail("credential_protection_unavailable")
        if not isinstance(value, bytes) or not value or len(value) > MAX_CIPHER_BYTES:
            _fail("credential_protection_failed")
        from ctypes import wintypes

        class Blob(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

        try:
            crypt = ctypes.WinDLL("crypt32", use_last_error=True)
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            crypt.CryptProtectData.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.POINTER(Blob),
                ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
            crypt.CryptUnprotectData.argtypes = [ctypes.POINTER(Blob), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(Blob),
                ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
            crypt.CryptProtectData.restype = crypt.CryptUnprotectData.restype = wintypes.BOOL
            kernel.LocalFree.argtypes = [ctypes.c_void_p]
            kernel.LocalFree.restype = ctypes.c_void_p
            buffer = ctypes.create_string_buffer(value)
            entropy_buffer = ctypes.create_string_buffer(b"ProducerPlease/platform-credentials/v1")
            incoming = Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
            entropy = Blob(len(entropy_buffer.raw) - 1, ctypes.cast(entropy_buffer, ctypes.POINTER(ctypes.c_ubyte)))
            outgoing = Blob()
            try:
                if decrypt:
                    success = crypt.CryptUnprotectData(ctypes.byref(incoming), None, ctypes.byref(entropy), None, None, 1, ctypes.byref(outgoing))
                else:
                    success = crypt.CryptProtectData(ctypes.byref(incoming), "Producer, Please platform credentials", ctypes.byref(entropy), None, None, 1, ctypes.byref(outgoing))
                if not success or not outgoing.pbData or not 0 < outgoing.cbData <= MAX_CIPHER_BYTES:
                    _fail("credential_protection_failed")
                return ctypes.string_at(outgoing.pbData, outgoing.cbData)
            finally:
                ctypes.memset(buffer, 0, len(value))
                if outgoing.pbData:
                    ctypes.memset(outgoing.pbData, 0, outgoing.cbData)
                    kernel.LocalFree(outgoing.pbData)
        except Exception:
            _fail("credential_protection_failed")

    def encrypt(self, value):
        return self._crypt(value)

    def decrypt(self, value):
        return self._crypt(value, decrypt=True)


def _owner_only(path):
    if not _windows_available():
        os.chmod(path, 0o600)
        return
    from ctypes import wintypes
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD)]
    convert.restype = wintypes.BOOL
    apply = advapi.SetFileSecurityW
    apply.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    apply.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    descriptor = ctypes.c_void_p()
    if not convert("D:P(A;;FA;;;OW)", 1, ctypes.byref(descriptor), None):
        _fail("credential_permissions_unavailable")
    try:
        if not apply(str(path), 0x80000004, descriptor):
            _fail("credential_permissions_unavailable")
    finally:
        kernel.LocalFree(descriptor)


def _json(raw):
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate field")
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=unique)
    except (ValueError, UnicodeError, TypeError):
        _fail("credential_storage_invalid")


def _provider(value):
    if not isinstance(value, str) or value not in PROVIDERS:
        _fail("invalid_credential_provider")
    return value


def _values(provider, values):
    limits = {**_STRINGS, **_CHANNELS[provider]}
    if not isinstance(values, dict) or set(values) - {*limits, "scopes", "expires_at"}:
        _fail("invalid_credential_fields")
    result = {}
    for key, value in values.items():
        if key in limits:
            if (not isinstance(value, str) or len(value) > limits[key]
                    or any(ord(char) < 32 or ord(char) == 127 for char in value)):
                _fail("invalid_credential_fields")
            result[key] = value
        elif key == "expires_at":
            if type(value) not in (int, float) or not 0 <= value <= 1e12 or not math.isfinite(value):
                _fail("invalid_credential_fields")
            result[key] = value
        else:
            if (not isinstance(value, list) or len(value) > 32
                    or any(not isinstance(scope, str) or not scope or len(scope) > 128
                           or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in scope) for scope in value)):
                _fail("invalid_credential_fields")
            result[key] = list(dict.fromkeys(value))
    return result


class PlatformCredentialVault:
    def __init__(self, path, *, cipher=None):
        requested = Path(path)
        if not requested.is_absolute():
            _fail("absolute_credential_path_required")
        self.path = _resolved(requested)
        source = _resolved(Path(__file__)).parents[2]
        if self.path == source or source in self.path.parents:
            _fail("credential_path_inside_source")
        self._cipher = cipher if cipher is not None else WindowsUserCipher()
        with _LOCKS_GUARD:
            self._lock = _LOCKS.setdefault(os.path.normcase(str(self.path)), threading.RLock())

    def _available(self):
        try:
            available = getattr(self._cipher, "available", True)
            return bool(available() if callable(available) else available) and all(callable(getattr(self._cipher, method, None)) for method in ("encrypt", "decrypt"))
        except Exception:
            return False

    def _load(self):
        if not self._available():
            _fail("credential_protection_unavailable")
        try:
            with self.path.open("rb") as handle:
                raw = handle.read(MAX_FILE_BYTES + 1)
        except FileNotFoundError:
            return {}, {}
        except OSError:
            _fail("credential_storage_unavailable")
        if len(raw) > MAX_FILE_BYTES:
            _fail("credential_storage_invalid")
        state = _json(raw)
        if (not isinstance(state, dict) or set(state) != {"version", "records"}
                or type(state["version"]) is not int or state["version"] != 1
                or not isinstance(state["records"], dict) or set(state["records"]) - set(PROVIDERS)):
            _fail("credential_storage_invalid")
        decoded = {}
        for provider, encoded in state["records"].items():
            try:
                if not isinstance(encoded, str) or not encoded or len(encoded) > 4 * MAX_CIPHER_BYTES // 3 + 8:
                    raise ValueError()
                protected = base64.b64decode(encoded, validate=True)
                if not protected or len(protected) > MAX_CIPHER_BYTES:
                    raise ValueError()
            except Exception:
                _fail("credential_storage_invalid")
            try:
                plaintext = self._cipher.decrypt(protected)
            except Exception:
                _fail("credential_decryption_failed")
            if not isinstance(plaintext, bytes) or len(plaintext) > MAX_RECORD_BYTES:
                _fail("credential_storage_invalid")
            payload = _json(plaintext)
            if (not isinstance(payload, dict) or set(payload) != {"version", "provider", "values"}
                    or type(payload["version"]) is not int or payload["version"] != 1 or payload["provider"] != provider):
                _fail("credential_storage_invalid")
            try:
                decoded[provider] = _values(provider, payload["values"])
            except PlatformCredentialsError:
                _fail("credential_storage_invalid")
        return state["records"], decoded

    def _persist(self, records):
        raw = json.dumps({"version": 1, "records": records}, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(raw) > MAX_FILE_BYTES:
            _fail("credential_storage_invalid")
        temporary = self.path.with_name("." + self.path.name + "." + uuid4().hex + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                _owner_only(temporary)
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except Exception:
            _fail("credential_storage_write_failed")
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _public(provider, value):
        if value is None:
            return {"state": "empty", "stored": False}
        result = {"state": "stored", "stored": True,
                  **{"has_" + key: bool(value.get(key)) for key in ("client_id", "client_secret", "access_token", "refresh_token")},
                  "has_channel": any(bool(value.get(key)) for key in _CHANNELS[provider])}
        if value.get("public_label"):
            result["public_label"] = value["public_label"]
        return result

    def snapshot(self):
        with self._lock:
            available = self._available()
            try:
                _, values = self._load()
                return {"state": "ready", "protection_available": available,
                        "providers": {provider: self._public(provider, values.get(provider)) for provider in PROVIDERS}}
            except PlatformCredentialsError as error:
                state = "locked" if error.code == "credential_decryption_failed" else "unavailable"
                return {"state": state, "protection_available": available,
                        "providers": {provider: {"state": state} for provider in PROVIDERS}}

    def status(self, provider):
        provider = _provider(provider)
        return self.snapshot()["providers"][provider]

    def get(self, provider):
        """Internal plaintext access only: never forward this result to a renderer."""
        provider = _provider(provider)
        with self._lock:
            value = self._load()[1].get(provider)
            return _values(provider, value) if value is not None else None

    def set(self, provider, values):
        """Merge supplied fields, preserving other fields/providers; never connect."""
        provider = _provider(provider)
        patch = _values(provider, values)
        with self._lock:
            records, decoded = self._load()
            value = {**decoded.get(provider, {}), **patch}
            if value == decoded.get(provider) or not value:
                return self._public(provider, decoded.get(provider))
            plaintext = json.dumps({"version": 1, "provider": provider, "values": value},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
            if len(plaintext) > MAX_RECORD_BYTES:
                _fail("invalid_credential_fields")
            try:
                protected = self._cipher.encrypt(plaintext)
                if not isinstance(protected, bytes) or not protected or len(protected) > MAX_CIPHER_BYTES:
                    raise ValueError()
            except Exception:
                _fail("credential_encryption_failed")
            self._persist({**records, provider: base64.b64encode(protected).decode("ascii")})
            return self._public(provider, value)

    def delete(self, provider):
        """Forget one local record only. Does not revoke authorization at a provider."""
        provider = _provider(provider)
        with self._lock:
            records, _ = self._load()
            if provider not in records:
                return False
            self._persist({key: value for key, value in records.items() if key != provider})
            return True
