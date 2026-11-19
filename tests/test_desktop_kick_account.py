"""Synthetic transport/vault coverage; no host credentials or provider connections."""
import asyncio
from copy import deepcopy
import hashlib
import io
import json
import sys

import httpx
import pytest

from rareiq.core.platform_credentials import PlatformCredentialVault
from tests.test_platform_credentials import TestCipher
from tools import desktop_kick_account as helper

NOW = 1800000000
REF = hashlib.sha256(b"kick:fixture-client:123").hexdigest()
SERVER = "rtmps://ingest.example.net:443/app"
RECORD = {"client_id": "fixture-client", "channel_id": "123", "channel_slug": "fixture_channel",
          "token_type": "bearer", "access_token": "synthetic-access", "refresh_token": "synthetic-refresh",
          "expires_at": NOW + 7200, "scopes": sorted(helper.SCOPES)}


class Vault:
    def __init__(self):
        self.value, self.reads = deepcopy(RECORD), 0

    def get(self, provider):
        assert provider == "kick"
        self.reads += 1
        return deepcopy(self.value)


class Fixture:
    def __init__(self):
        self.now, self.vault, self.calls, self.hook = NOW, Vault(), [], None
        self.auth = {"active": True, "token_type": "user", "client_id": "fixture-client",
                     "scope": " ".join(sorted(helper.SCOPES)), "exp": NOW + 7100}
        self.channel = {"broadcaster_user_id": 123, "slug": "fixture_channel",
                        "stream": {"url": SERVER, "key": "synthetic-private-key"}}
        self.responses = {}

    async def http(self, request):
        endpoint = str(request.url)
        self.calls.append((request.method, endpoint))
        assert request.headers["Authorization"] == "Bearer synthetic-access"
        assert not request.url.query and request.content == b""
        assert (request.method, endpoint) in {("POST", helper.INTROSPECT_URL), ("GET", helper.CHANNELS_URL)}
        if self.hook:
            self.hook(request)
        if endpoint in self.responses:
            return self.responses[endpoint]
        value = self.auth if endpoint == helper.INTROSPECT_URL else [self.channel]
        return httpx.Response(200, json={"data": value})

    async def resolve(self, ref=REF):
        return await helper.resolve_stream_key(ref, vault=self.vault, clock=lambda: self.now,
            http_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(self.http)))


@pytest.fixture(autouse=True)
def no_host_configuration(monkeypatch):
    monkeypatch.delenv("RAREIQ_KICK_CLIENT_ID", raising=False)


def test_private_resolution_verifies_fixed_endpoints_without_writes():
    f = Fixture()
    assert asyncio.run(f.resolve()) == {"ok": True, "platform": "kick", "accountRef": REF,
                                      "serverUrl": SERVER, "streamKey": "synthetic-private-key"}
    assert f.calls == [("POST", helper.INTROSPECT_URL), ("GET", helper.CHANNELS_URL)]
    assert f.vault.value == RECORD and f.vault.reads == 2


@pytest.mark.parametrize("failure,reason", [
    ("invalid_ref", "invalid_account_request"), ("other_platform_ref", "account_identity_mismatch"),
    ("configured_client", "account_identity_mismatch"), ("record_scope", "streaming_scope_required"),
    ("record_expiry", "authorization_refresh_required"), ("record_identity", "authorization_required"),
    ("inactive", "authorization_rejected"), ("wrong_client", "authorization_rejected"),
    ("app_token", "authorization_rejected"), ("provider_scope", "streaming_scope_required"),
    ("provider_expiry", "authorization_refresh_required"), ("wrong_channel", "account_identity_mismatch"),
    ("bool_channel", "account_identity_mismatch"), ("malformed_slug", "account_identity_mismatch"),
    ("missing_key", "streaming_not_available"), ("malformed_key", "invalid_provider_response"),
    ("missing_ingest", "streaming_not_available"), ("insecure_ingest", "secure_ingest_unavailable"),
    ("rejected", "authorization_rejected"), ("forbidden", "streaming_not_available"),
    ("redirect", "provider_unavailable"), ("invalid_json", "invalid_provider_response"),
    ("non_json", "invalid_provider_response"), ("oversized", "provider_response_too_large"),
    ("multiple_channels", "kick_channel_required"), ("refreshed", "account_state_changed"),
    ("disconnected", "account_state_changed"), ("network_expiry", "authorization_refresh_required"),
])
def test_private_resolution_failures_return_only_constant_reasons(monkeypatch, failure, reason):
    f, ref = Fixture(), REF
    if failure == "invalid_ref":
        ref = "malformed"
    elif failure == "other_platform_ref":
        ref = hashlib.sha256(b"fixture-client:123").hexdigest()
    elif failure == "configured_client":
        monkeypatch.setenv("RAREIQ_KICK_CLIENT_ID", "different-app")
    elif failure == "record_scope":
        f.vault.value["scopes"] = ["user:read", "channel:read"]
    elif failure == "record_expiry":
        f.vault.value["expires_at"] = NOW + 30
    elif failure == "record_identity":
        f.vault.value["channel_id"] = True
    elif failure == "inactive":
        f.auth["active"] = False
    elif failure == "wrong_client":
        f.auth["client_id"] = "different-app"
    elif failure == "app_token":
        f.auth["token_type"] = "app"
    elif failure == "provider_scope":
        f.auth["scope"] = "user:read channel:read"
    elif failure == "provider_expiry":
        f.auth["exp"] = NOW + 30
    elif failure == "wrong_channel":
        f.channel["broadcaster_user_id"] = 999
    elif failure == "bool_channel":
        f.channel["broadcaster_user_id"] = True
    elif failure == "malformed_slug":
        f.channel["slug"] = "private\nslug"
    elif failure == "missing_key":
        f.channel["stream"].pop("key")
    elif failure == "malformed_key":
        f.channel["stream"]["key"] = "private\nkey"
    elif failure == "missing_ingest":
        f.channel["stream"].pop("url")
    elif failure == "insecure_ingest":
        f.channel["stream"]["url"] = "rtmp://ingest.example.net/app"
    elif failure == "rejected":
        f.responses[helper.INTROSPECT_URL] = httpx.Response(401, json={"message": "private provider message"})
    elif failure == "forbidden":
        f.responses[helper.CHANNELS_URL] = httpx.Response(403, json={"message": "private provider message"})
    elif failure == "redirect":
        f.responses[helper.CHANNELS_URL] = httpx.Response(302, headers={"Location": "https://other.invalid/private"})
    elif failure == "invalid_json":
        f.responses[helper.CHANNELS_URL] = httpx.Response(200, content=b"{private", headers={"Content-Type": "application/json"})
    elif failure == "non_json":
        f.responses[helper.CHANNELS_URL] = httpx.Response(200, content=b"{}", headers={"Content-Type": "text/html"})
    elif failure == "oversized":
        f.responses[helper.CHANNELS_URL] = httpx.Response(200, content=b"x" * (helper.MAX_BYTES + 1), headers={"Content-Type": "application/json"})
    elif failure == "multiple_channels":
        f.responses[helper.CHANNELS_URL] = httpx.Response(200, json={"data": [f.channel, f.channel]})
    elif failure in {"refreshed", "disconnected", "network_expiry"}:
        def hook(request):
            if str(request.url) == helper.CHANNELS_URL:
                if failure == "refreshed":
                    f.vault.value["access_token"] = "synthetic-newer-access"
                elif failure == "disconnected":
                    f.vault.value = {"client_id": "fixture-client"}
                else:
                    f.now += 7200
        f.hook = hook
    with pytest.raises(helper.AccountError) as exc:
        asyncio.run(f.resolve(ref))
    assert str(exc.value) == reason and all(value not in str(exc.value) for value in ("synthetic", "private"))


@pytest.mark.parametrize("url", ["rtmp://ingest.example.net/app", "https://ingest.example.net/app",
    "rtmps://127.0.0.1/app", "rtmps://[::1]/app", "rtmps://192.168.1.2/app", "rtmps://localhost/app",
    "rtmps://ingest.local/app", "rtmps://2130706433/app", "rtmps://127.1/app"])
def test_insecure_or_nonpublic_ingest_is_never_rewritten_or_returned(url):
    with pytest.raises(helper.AccountError, match="secure_ingest_unavailable"):
        helper._server_url(url)


@pytest.mark.parametrize("url", ["rtmps://name:private@ingest.example.net/app", "rtmps://ingest.example.net/app?key=private",
    "rtmps://ingest.example.net/app#private", "rtmps://ingest.example.net:0/app", "rtmps://ingest.example.net:99999/app",
    "rtmps://ingest.example.net:/app",
    "rtmps://ingest.example.net/pri vate", "rtmps://ingest.example.net/priv\nate", "rtmps://ingest.example.net\\private/app",
    "rtmps://ingest.example.net/app?", "rtmps://ingest.example.net/app#"])
def test_malformed_ingest_cannot_smuggle_credentials_or_query_data(url):
    with pytest.raises(helper.AccountError, match="invalid_provider_response"):
        helper._server_url(url)


def test_encrypted_vault_is_reopened_without_modifying_file(tmp_path):
    vault = PlatformCredentialVault(tmp_path / "accounts.enc.json", cipher=TestCipher())
    vault.set("kick", RECORD)
    before = vault.path.read_bytes()
    f = Fixture()
    f.vault = PlatformCredentialVault(vault.path, cipher=TestCipher())
    assert asyncio.run(f.resolve())["accountRef"] == REF
    assert vault.path.read_bytes() == before and b"synthetic-access" not in before


@pytest.mark.parametrize("body", [b"{}", b"[]", b'{"accountRef":"bad"}', b"x" * 513,
    json.dumps({"accountRef": REF, "extra": "private"}).encode()])
def test_cli_invalid_input_is_bounded_redacted_and_does_not_access_vault(monkeypatch, capsys, body):
    monkeypatch.setattr(sys, "argv", ["desktop_kick_account.py"])
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(body), encoding="utf-8"))
    monkeypatch.setattr(helper, "PlatformCredentialVault", lambda *_: pytest.fail("Invalid input accessed vault"))
    assert helper.main() == 2
    assert json.loads(capsys.readouterr().out) == {"ok": False, "reason": "invalid_account_request"}


def test_origin_only_secure_ingest_and_provider_key_are_returned_without_inventing_an_application_path():
    f = Fixture()
    f.channel["stream"]["url"] = "rtmps://ingest.example.net:443"
    f.channel["stream"]["key"] = "app/synthetic-private-key"
    value = asyncio.run(f.resolve())
    assert value["serverUrl"] == "rtmps://ingest.example.net:443"
    assert value["streamKey"] == "app/synthetic-private-key"
