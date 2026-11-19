from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
import os
from pathlib import Path

import pytest

from rareiq.core import platform_credentials as credentials


class TestCipher:
    __test__ = False
    available = True

    def __init__(self, key=b"synthetic authenticated test cipher"):
        self.key = hashlib.sha256(key).digest()
        self.encrypt_calls = self.decrypt_calls = 0

    def encrypt(self, value):
        self.encrypt_calls += 1
        body = bytes(byte ^ self.key[index % len(self.key)] for index, byte in enumerate(value))
        return hmac.digest(self.key, body, "sha256") + body

    def decrypt(self, value):
        self.decrypt_calls += 1
        signature, body = value[:32], value[32:]
        if not hmac.compare_digest(signature, hmac.digest(self.key, body, "sha256")):
            raise ValueError("synthetic private provider failure")
        return bytes(byte ^ self.key[index % len(self.key)] for index, byte in enumerate(body))


@pytest.fixture
def vault(tmp_path):
    cipher = TestCipher()
    return credentials.PlatformCredentialVault(tmp_path / "profile/platform-credentials.json", cipher=cipher)


def test_construct_and_empty_reads_create_no_profile(vault):
    assert not vault.path.parent.exists()
    assert vault.get("twitch") is None
    assert vault.snapshot()["state"] == "ready"
    assert vault.status("twitch") == {"state": "empty", "stored": False}
    assert vault.delete("twitch") is False
    assert not vault.path.parent.exists()


def test_explicit_absolute_outside_source_path_is_required():
    with pytest.raises(credentials.PlatformCredentialsError, match="absolute_credential_path_required"):
        credentials.PlatformCredentialVault("relative.json", cipher=TestCipher())
    with pytest.raises(credentials.PlatformCredentialsError, match="credential_path_inside_source"):
        credentials.PlatformCredentialVault(Path(credentials.__file__).resolve().parents[2] / "private.json", cipher=TestCipher())
    if os.name == "nt":
        extended = "\\\\?\\" + str(Path(credentials.__file__).resolve().parents[2] / "private.json")
        with pytest.raises(credentials.PlatformCredentialsError, match="credential_path_inside_source"):
            credentials.PlatformCredentialVault(extended, cipher=TestCipher())


def test_merge_idempotence_reload_and_public_redaction(vault):
    values = {"client_id": "synthetic-private-client-id", "channel_id": "synthetic-channel-id",
              "client_secret": "synthetic-private-client-secret", "access_token": "synthetic-private-access-token",
              "refresh_token": "synthetic-private-refresh-token", "public_label": "Public channel", "scopes": ["user:read:chat"]}
    status = vault.set("twitch", values)
    assert status["stored"] and status["has_client_id"] and status["has_channel"]
    assert status["public_label"] == "Public channel"
    text = json.dumps(vault.snapshot())
    assert all(value not in text for key, value in values.items() if key not in {"public_label", "scopes"})
    on_disk = vault.path.read_bytes()
    assert all(value.encode() not in on_disk for key, value in values.items() if isinstance(value, str))
    vault.set("twitch", dict(values))
    assert vault.path.read_bytes() == on_disk and vault._cipher.encrypt_calls == 1
    vault.set("twitch", {"access_token": "synthetic-replacement", "expires_at": 1795060000.25})
    reloaded = credentials.PlatformCredentialVault(vault.path, cipher=TestCipher())
    result = reloaded.get("twitch")
    assert result["client_secret"] == values["client_secret"]
    assert result["access_token"] == "synthetic-replacement" and result["expires_at"] == 1795060000.25
    result["scopes"].append("changed")
    assert reloaded.get("twitch")["scopes"] == ["user:read:chat"]


def test_public_client_setup_without_secret_or_tokens_and_unicode(vault):
    value = {"client_id": "public-client", "public_label": "朗读频道 🎧", "channel_name": "欢迎直播", "scopes": []}
    status = vault.set("youtube", value)
    assert status["has_client_id"] and not status["has_client_secret"] and not status["has_access_token"]
    assert vault.get("youtube") == value
    assert vault.path.read_bytes().find("欢迎直播".encode()) == -1


def test_provider_bindings_reject_swapped_ciphertext_without_overwrite(vault):
    vault.set("twitch", {"access_token": "synthetic-twitch"})
    vault.set("youtube", {"access_token": "synthetic-youtube"})
    state = json.loads(vault.path.read_text())
    state["records"]["twitch"], state["records"]["youtube"] = state["records"]["youtube"], state["records"]["twitch"]
    vault.path.write_text(json.dumps(state))
    before = vault.path.read_bytes()
    with pytest.raises(credentials.PlatformCredentialsError, match="credential_storage_invalid"):
        vault.set("kick", {"client_id": "new-client"})
    assert vault.path.read_bytes() == before


def test_wrong_cipher_or_corruption_is_locked_and_never_replaced(vault):
    vault.set("twitch", {"access_token": "synthetic-access"})
    before = vault.path.read_bytes()
    wrong = credentials.PlatformCredentialVault(vault.path, cipher=TestCipher(b"wrong synthetic user key"))
    assert wrong.snapshot()["state"] == "locked"
    for action in (lambda: wrong.get("twitch"), lambda: wrong.set("youtube", {"client_id": "new"}), lambda: wrong.delete("twitch")):
        with pytest.raises(credentials.PlatformCredentialsError, match="credential_decryption_failed") as error:
            action()
        assert "provider failure" not in str(error.value)
        assert vault.path.read_bytes() == before


@pytest.mark.parametrize("raw", [b"not json", b"{}", b"[]", b'{"version":true,"records":{}}',
    b'{"version":1,"version":1,"records":{}}', b'{"version":1,"records":{"unknown":"value"}}',
    b'{"version":1,"records":{"twitch":"not-base64!"}}', b"x" * (credentials.MAX_FILE_BYTES + 1)],
    ids=['invalid-json', 'missing-schema', 'wrong-container', 'bool-version', 'duplicate-version', 'unknown-provider', 'invalid-ciphertext', 'oversized'])
def test_bad_existing_storage_is_preserved(vault, raw):
    vault.path.parent.mkdir(parents=True)
    vault.path.write_bytes(raw)
    assert vault.snapshot()["state"] == "unavailable"
    with pytest.raises(credentials.PlatformCredentialsError, match="credential_storage_invalid"):
        vault.set("twitch", {"client_id": "replacement"})
    assert vault.path.read_bytes() == raw


@pytest.mark.parametrize("record", [{"unknown": "value"}, {"channel_slug": "not-a-twitch-field"},
    {"client_id": "x" * 513}, {"client_secret": "x" * 4097}, {"public_label": "bad\nlabel"},
    {"access_token": None}, {"expires_at": True}, {"expires_at": float("nan")}, {"expires_at": float("inf")},
    {"expires_at": -1}, {"scopes": "read"}, {"scopes": ["contains whitespace"]}, {"scopes": ["x"] * 33}])
def test_invalid_fields_do_not_create_vault(vault, record):
    with pytest.raises(credentials.PlatformCredentialsError, match="invalid_credential_fields"):
        vault.set("twitch", record)
    assert not vault.path.parent.exists()


def test_unknown_provider_rejects_before_credentials_are_read(vault):
    vault.set("twitch", {"access_token": "synthetic-access"})
    calls = vault._cipher.decrypt_calls
    for action in (lambda: vault.get("other"), lambda: vault.status("other"),
                   lambda: vault.set("other", {}), lambda: vault.delete("other")):
        with pytest.raises(credentials.PlatformCredentialsError, match="invalid_credential_provider"):
            action()
    assert vault._cipher.decrypt_calls == calls


def test_failed_atomic_replace_or_permissions_preserves_previous_records(vault, monkeypatch):
    vault.set("twitch", {"client_id": "original"})
    before = vault.path.read_bytes()
    def failure(*_args):
        raise OSError("synthetic secret should not escape")
    with monkeypatch.context() as patch:
        patch.setattr(credentials.os, "replace", failure)
        with pytest.raises(credentials.PlatformCredentialsError, match="credential_storage_write_failed") as error:
            vault.set("youtube", {"client_id": "replacement"})
        assert "synthetic secret" not in str(error.value)
    with monkeypatch.context() as patch:
        patch.setattr(credentials, "_owner_only", failure)
        with pytest.raises(credentials.PlatformCredentialsError, match="credential_storage_write_failed"):
            vault.set("youtube", {"client_id": "replacement"})
    assert vault.path.read_bytes() == before
    assert list(vault.path.parent.glob(".*.tmp")) == []
    assert vault.get("twitch")["client_id"] == "original"


def test_read_failure_is_unavailable_and_cannot_replace_existing_credentials(vault, monkeypatch):
    vault.set("twitch", {"client_id": "synthetic-original"})
    before = vault.path.read_bytes()
    original = Path.open
    def denied(path, *args, **kwargs):
        if path == vault.path:
            raise PermissionError("synthetic private path detail")
        return original(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", denied)
        assert vault.snapshot()["state"] == "unavailable"
        with pytest.raises(credentials.PlatformCredentialsError, match="credential_storage_unavailable") as error:
            vault.set("youtube", {"client_id": "replacement"})
        assert "private path" not in str(error.value)
    assert vault.path.read_bytes() == before


def test_encryption_failure_and_unsupported_default_never_write(vault, monkeypatch):
    def failure(_value):
        raise RuntimeError("synthetic private encryption error")
    monkeypatch.setattr(vault._cipher, "encrypt", failure)
    with pytest.raises(credentials.PlatformCredentialsError, match="credential_encryption_failed"):
        vault.set("twitch", {"client_id": "synthetic"})
    assert not vault.path.exists()
    monkeypatch.setattr(credentials, "_windows_available", lambda: False)
    unsupported = credentials.PlatformCredentialVault(vault.path)
    assert unsupported.snapshot()["state"] == "unavailable"
    assert unsupported.snapshot()["protection_available"] is False
    with pytest.raises(credentials.PlatformCredentialsError, match="credential_protection_unavailable"):
        unsupported.set("twitch", {"client_id": "synthetic"})
    assert not vault.path.exists()


def test_separate_instances_share_lock_and_preserve_provider_updates(vault):
    if os.name == "nt":
        alias = credentials.PlatformCredentialVault("\\\\?\\" + str(vault.path), cipher=TestCipher())
        assert alias._lock is vault._lock
    patches = [("twitch", {"client_id": "synthetic-client"}), ("twitch", {"refresh_token": "synthetic-refresh"}),
               ("youtube", {"client_secret": "synthetic-youtube"}), ("kick", {"channel_slug": "synthetic-kick"})]
    def update(item):
        provider, value = item
        credentials.PlatformCredentialVault(vault.path, cipher=TestCipher()).set(provider, value)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(update, patches * 4))
    assert vault.get("twitch") == {"client_id": "synthetic-client", "refresh_token": "synthetic-refresh"}
    assert vault.get("youtube")["client_secret"] == "synthetic-youtube"
    assert vault.get("kick")["channel_slug"] == "synthetic-kick"


def test_local_forgetting_preserves_other_provider_and_is_idempotent(vault):
    vault.set("twitch", {"access_token": "synthetic-access"})
    vault.set("kick", {"client_id": "synthetic-client"})
    assert vault.delete("twitch") is True
    before = vault.path.read_bytes()
    assert vault.delete("twitch") is False and vault.path.read_bytes() == before
    assert vault.get("kick")["client_id"] == "synthetic-client"


@pytest.mark.skipif(os.name != "nt", reason="CurrentUser DPAPI and Windows DACL acceptance")
def test_real_windows_dpapi_synthetic_round_trip_and_owner_only_acl(tmp_path):
    from ctypes import wintypes
    import ctypes
    path = tmp_path / "synthetic-windows/platform-credentials.json"
    vault = credentials.PlatformCredentialVault(path)
    marker = "synthetic-real-dpapi-token-朗读"
    vault.set("twitch", {"client_id": "synthetic-client", "access_token": marker})
    assert credentials.PlatformCredentialVault(path).get("twitch")["access_token"] == marker
    assert marker.encode() not in path.read_bytes()
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi.GetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(wintypes.DWORD)]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    size = wintypes.DWORD()
    advapi.GetFileSecurityW(str(path), 4, None, 0, ctypes.byref(size))
    buffer = ctypes.create_string_buffer(size.value)
    assert advapi.GetFileSecurityW(str(path), 4, buffer, size.value, ctypes.byref(size))
    sddl = wintypes.LPWSTR()
    assert advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW(buffer, 1, 4, ctypes.byref(sddl), None)
    try:
        assert sddl.value.startswith("D:P")
        assert ";;;OW)" in sddl.value or ";;;S-1-3-4)" in sddl.value
        assert all(trustee not in sddl.value for trustee in (";;;WD)", ";;;BU)", ";;;AU)", ";;;BA)"))
    finally:
        kernel.LocalFree(sddl)
