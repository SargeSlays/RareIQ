"""Synthetic local configuration only; no provider or real credential access."""
import asyncio
import copy
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from rareiq.services.platform_app_setup import PlatformAppSetupService, AppSetupError
from rareiq.web.platform_app_setup import create_platform_app_setup_router

CONFIG = {"client_id": "fixture.apps.googleusercontent.com", "client_secret": "synthetic-private-setup"}


class Vault:
    def __init__(self):
        self.records = {"twitch": {"access_token": "synthetic-other-provider"}}
        self.writes = 0
    def get(self, provider):
        return copy.deepcopy(self.records.get(provider))
    def set(self, provider, patch):
        self.writes += 1
        self.records[provider] = {**self.records.get(provider, {}), **patch}


def fixture(audit=None):
    vault = Vault()
    owners = {p: SimpleNamespace(_credential_lock=asyncio.Lock(), _closed=False, _pending=None,
                                _generation=2, _reason="app_setup_required") for p in ["youtube", "kick"]}
    service = PlatformAppSetupService(vault, owners, environment={})
    app = FastAPI()
    app.include_router(create_platform_app_setup_router(service, lambda _: True, audit=audit))
    client = TestClient(app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 9000))
    return vault, owners, service, client


def test_configuration_is_atomic_idempotent_and_retains_other_provider():
    async def run():
        vault, owners, service, _ = fixture()
        first = await service.configure("youtube", CONFIG)
        assert first == {"configured": True, "replayed": False, "platform": "youtube"}
        assert (await service.configure("youtube", CONFIG))["replayed"]
        assert vault.writes == 1 and owners["youtube"]._generation == 3
        assert vault.get("twitch") == {"access_token": "synthetic-other-provider"}
        assert "synthetic-private" not in str(first)
    asyncio.run(run())


def test_pending_auth_existing_tokens_and_external_configuration_cannot_be_overwritten():
    async def run():
        vault, owners, service, _ = fixture()
        owners["youtube"]._pending = {"flow_id": "a" * 32}
        with pytest.raises(AppSetupError, match="disconnect_before_app_setup"):
            await service.configure("youtube", CONFIG)
        owners["youtube"]._pending = None
        vault.records["youtube"] = {"refresh_token": "synthetic-saved-token"}
        with pytest.raises(AppSetupError, match="disconnect_before_app_setup"):
            await service.configure("youtube", CONFIG)
        assert vault.writes == 0
        service._environment = {"RAREIQ_KICK_CLIENT_ID": "environment-app", "RAREIQ_KICK_CLIENT_SECRET": "synthetic-env"}
        with pytest.raises(AppSetupError, match="external_app_configuration_active"):
            await service.configure("kick", {"client_id": "new-app", "client_secret": "synthetic-new"})
    asyncio.run(run())


def test_invalid_fields_provider_and_storage_failure_do_not_leak_or_advance_owner():
    async def run():
        vault, owners, service, _ = fixture()
        for provider, value in [("twitch", CONFIG), ("youtube", {**CONFIG, "access_token": "secret"}),
                                ("youtube", {**CONFIG, "client_id": "bad"}), ("kick", {"client_id": "app", "client_secret": "bad secret"})]:
            with pytest.raises(AppSetupError):
                await service.configure(provider, value)
        def fail(*_):
            raise OSError("private filename and secret")
        vault.set = fail
        with pytest.raises(AppSetupError, match="^account_storage_unavailable$"):
            await service.configure("youtube", CONFIG)
        assert owners["youtube"]._generation == 2
    asyncio.run(run())


def test_real_routes_require_local_same_origin_operator_and_bound_private_body():
    vault, _, _, client = fixture()
    path = "/api/production/accounts/youtube/configure-app"
    assert client.post(path, json=CONFIG).status_code == 403
    assert client.post(path, json=CONFIG, headers={"Origin": "https://foreign.invalid"}).status_code == 403
    headers = {"Origin": "http://127.0.0.1:8765"}
    assert client.post(path, content="x" * 16385, headers={**headers, "Content-Type": "application/json"}).status_code == 400
    result = client.post(path, json=CONFIG, headers=headers)
    assert result.status_code == 200 and result.json()["configured"]
    assert "synthetic-private" not in result.text and "client_secret" not in result.text
    assert vault.writes == 1


def test_audit_failure_before_write_blocks_and_failure_after_write_warns_without_retry_failure():
    calls = []
    def fail_before(**entry):
        raise OSError("secret")
    vault, _, _, client = fixture(fail_before)
    path = "/api/production/accounts/youtube/configure-app"
    headers = {"Origin": "http://127.0.0.1:8765"}
    assert client.post(path, json=CONFIG, headers=headers).status_code == 503
    assert vault.writes == 0
    def fail_after(**entry):
        calls.append(entry)
        if entry["outcome"] == "configured":
            raise OSError("private path")
    vault, _, _, client = fixture(fail_after)
    value = client.post(path, json=CONFIG, headers=headers).json()
    assert value["ok"] and value["activity_history_warning"] and vault.writes == 1
    assert calls == [{"action": "youtube.configure_app", "outcome": "requested"},
                     {"action": "youtube.configure_app", "outcome": "configured"}]


def test_import_shares_the_provider_credential_lock_and_does_not_restore_auth():
    async def run():
        vault, owners, service, _ = fixture()
        async with owners["kick"]._credential_lock:
            task = asyncio.create_task(service.configure("kick", {"client_id": "kick-app", "client_secret": "synthetic-setup"}))
            await asyncio.sleep(0)
            assert not task.done() and vault.writes == 0
            vault.records["kick"] = {"access_token": "newly-saved-auth"}
        with pytest.raises(AppSetupError, match="disconnect_before_app_setup"):
            await task
        assert vault.writes == 0
    asyncio.run(run())
