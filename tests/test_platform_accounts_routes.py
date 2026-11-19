"""In-memory HTTP boundaries only; no provider requests, files or credentials."""
import asyncio
import json
from urllib.parse import urlencode

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from rareiq.web import platform_accounts as routes


ORIGIN = "http://127.0.0.1:8765"
PATH = "/api/production/accounts"


class Account:
    def __init__(self):
        self.value = {"platform": "twitch", "state": "not_authorized", "reason": "authorization_required",
                      "authorized": False, "app_configured": True}
        self.status_calls = self.begins = self.cancels = self.connects = 0

    def status(self):
        self.status_calls += 1
        return dict(self.value)

    async def begin(self):
        self.begins += 1
        self.value.update(state="pending", reason="authorization_pending", user_code="CODE-1234",
                          flow_id="a" * 32, verification_url="https://untrusted.example/activate",
                          expires_at=1795060000.5, poll_after=5,
                          device_code="private-device-code", access_token="private-access-token",
                          client_id="private-client-id", device_token="private-device-token")
        return {"private_begin_result": "private-secret"}

    async def cancel(self):
        self.cancels += 1
        self.value.update(state="authorized" if self.value.get("authorized") else "not_authorized",
                          reason="authorization_cancelled")


class Vault:
    def __init__(self):
        self.records = {"youtube": {"state": "stored", "stored": True, "has_client_id": True,
            "has_refresh_token": True, "public_label": "Public channel", "client_id": "private-client-id",
            "refresh_token": "private-refresh-token", "authorized": True},
            "kick": {"state": "empty", "stored": False}}

    def status(self, provider):
        return dict(self.records[provider])


def fixture(*, host="127.0.0.1", origin=ORIGIN, authorized=True, audit=None, youtube=None):
    service, vault, app = Account(), Vault(), FastAPI()
    app.include_router(routes.create_platform_accounts_router(service, lambda request: authorized, vault=vault, audit=audit, youtube_service=youtube))
    return service, vault, app, TestClient(app, base_url=origin, client=(host, 1234))


def test_status_is_read_only_and_redacts_configuration_and_provider_data():
    service, vault, _, client = fixture()
    assert service.status_calls == 0
    for _ in range(2):
        reply = client.get(PATH)
        assert reply.status_code == 200 and reply.headers["cache-control"] == "no-store"
        accounts = reply.json()["accounts"]
        assert [item["platform"] for item in accounts] == ["twitch", "youtube", "kick"]
        assert accounts[0]["app_configured"] is True
        assert accounts[1]["stored"] and accounts[1]["has_refresh_token"]
        assert accounts[1]["authorized"] is False and accounts[1]["reason"] == "youtube_sign_in_setup_required"
        assert accounts[2]["authorized"] is False and accounts[2]["reason"] == "kick_public_callback_required"
        assert "private-" not in reply.text
    assert service.status_calls == 2 and service.begins == service.cancels == service.connects == 0


@pytest.mark.parametrize("options", [{"host": "198.51.100.7"}, {"origin": "http://rebind.example:8765"}, {"authorized": False}])
def test_all_routes_require_local_client_local_host_and_operator(options):
    service, _, _, client = fixture(**options)
    assert client.get(PATH).status_code == 403
    for action in ("begin", "cancel"):
        assert client.post(PATH + "/twitch/" + action, json={}, headers={"Origin": ORIGIN}).status_code == 403
    assert service.status_calls == service.begins == service.cancels == 0


@pytest.mark.parametrize("headers", [{"Origin": "https://outside.example"}, {"Origin": "null"},
    {"Origin": ORIGIN, "Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"}])
def test_cross_origin_status_and_commands_are_rejected(headers):
    service, _, _, client = fixture()
    assert client.get(PATH, headers=headers).status_code == 403
    assert client.post(PATH + "/twitch/begin", json={}, headers=headers).status_code == 403
    assert service.status_calls == service.begins == 0


def test_commands_require_origin_and_reject_duplicate_origin_headers():
    service, _, _, client = fixture()
    assert client.post(PATH + "/twitch/begin", json={}).status_code == 403
    headers = [("Origin", ORIGIN), ("Origin", ORIGIN)]
    assert client.post(PATH + "/twitch/begin", json={}, headers=headers).status_code == 403
    assert service.begins == 0


def test_pending_human_code_is_local_only_and_verification_url_is_fixed():
    audits = []
    service, _, _, client = fixture(audit=lambda **entry: audits.append(entry))
    reply = client.post(PATH + "/twitch/begin", json={}, headers={"Origin": ORIGIN})
    assert reply.status_code == 200 and reply.headers["cache-control"] == "no-store"
    value = reply.json()["account"]
    assert value["user_code"] == "CODE-1234" and value["flow_id"] == "a" * 32
    assert value["verification_url"] == "https://www.twitch.tv/activate"
    assert value["expires_at"] == 1795060000.5 and value["poll_after"] == 5
    assert all(marker not in reply.text for marker in ("private-", "untrusted.example", "private_begin_result"))
    assert client.get(PATH).json()["accounts"][0] == value
    assert client.get(PATH, headers={"Origin": "https://outside.example"}).status_code == 403
    assert audits == [{"action": "twitch.begin", "outcome": "requested"},
                      {"action": "twitch.begin", "outcome": "pending"}]
    assert service.begins == 1


def test_cancel_keeps_saved_authorization_and_audits_no_credentials():
    audits = []
    service, vault, _, client = fixture(audit=lambda **entry: audits.append(entry))
    service.value.update(state="pending", reason="authorization_pending", authorized=True, user_code="CODE-1234", flow_id="b" * 32)
    before = json.dumps(vault.records)
    reply = client.post(PATH + "/twitch/cancel", json={}, headers={"Origin": ORIGIN})
    assert reply.status_code == 200
    assert reply.json()["account"]["authorized"] is True
    assert "user_code" not in reply.text and "private-" not in reply.text
    assert json.dumps(vault.records) == before and service.cancels == 1
    assert audits == [{"action": "twitch.cancel", "outcome": "requested"},
                      {"action": "twitch.cancel", "outcome": "authorized"}]


@pytest.mark.parametrize("body,content_type", [(b"{", "application/json"), (b"", "application/json"),
    (b"\xff", "application/json"), (b"[]", "application/json"), (b"{}", "text/plain"),
    (b'{"client_id":"private-client-id"}', "application/json"), (b" " * 127 + b"{}", "application/json")])
def test_only_bounded_empty_json_commands_can_start_a_flow(body, content_type):
    service, _, _, client = fixture()
    reply = client.post(PATH + "/twitch/begin", content=body, headers={"Origin": ORIGIN, "Content-Type": content_type})
    assert reply.status_code == 400 and reply.json()["reason"] == "empty_command_required"
    assert service.begins == 0 and "private-" not in reply.text


def test_chunked_body_size_limit_without_content_length():
    service, _, _, client = fixture()
    reply = client.post(PATH + "/twitch/begin", content=iter([b" " * 100, b" " * 100]),
                        headers={"Origin": ORIGIN, "Content-Type": "application/json"})
    assert reply.status_code == 400 and service.begins == 0


def test_stalled_body_is_cancelled_before_action(monkeypatch):
    service, _, app, _ = fixture()
    monkeypatch.setattr(routes, "BODY_TIMEOUT_SECONDS", .01)
    async def exercise():
        sent = []
        async def receive():
            await asyncio.sleep(60)
        async def send(message):
            sent.append(message)
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
            "scheme": "http", "path": PATH + "/twitch/begin", "raw_path": (PATH + "/twitch/begin").encode(),
            "root_path": "", "query_string": b"", "server": ("127.0.0.1", 8765), "client": ("127.0.0.1", 1234),
            "headers": [(b"host", b"127.0.0.1:8765"), (b"origin", ORIGIN.encode()), (b"content-type", b"application/json")]}
        await asyncio.wait_for(app(scope, receive, send), .5)
        assert sent[0]["status"] == 400
    asyncio.run(exercise())
    assert service.begins == 0


@pytest.mark.parametrize("where", ["status", "begin", "vault", "audit"])
def test_unknown_exceptions_return_only_constant_unavailable(where):
    def failure(*_args, **_kwargs):
        raise RuntimeError("private-token-and-provider-error")
    service, vault, app, client = fixture(audit=failure if where == "audit" else None)
    if where == "vault":
        vault.status = failure
    elif where != "audit":
        setattr(service, where, failure)
    reply = client.post(PATH + "/twitch/begin", json={}, headers={"Origin": ORIGIN}) if where in {"begin", "audit"} else client.get(PATH)
    assert reply.status_code == 503 and reply.json() == {"ok": False, "reason": "account_unavailable"}
    assert "private-" not in reply.text
    if where == "audit":
        assert service.begins == 0


def test_corrupt_vault_metadata_and_untrusted_status_fields_never_escape():
    service, vault, _, client = fixture()
    vault.records["youtube"].update(state="locked", stored=True)
    service.value.update(state="arbitrary private state", reason="private-access-token", authorized=True,
                         client_id="private-client-id", user_code="private-code", device_code="private-device-code")
    reply = client.get(PATH)
    assert reply.status_code == 200 and "private-" not in reply.text
    twitch, youtube, _ = reply.json()["accounts"]
    assert twitch["state"] == "unavailable" and twitch["authorized"] is False
    assert youtube["storage_state"] == "locked" and youtube["stored"] is False and youtube["authorized"] is False


def test_invalid_pending_code_does_not_expose_a_partial_flow():
    service, _, _, client = fixture()
    service.value.update(state="pending", reason="authorization_pending", flow_id="not-a-flow", user_code="PRIVATE\nCODE", expires_at=float("nan"))
    reply = client.get(PATH)
    account = reply.json()["accounts"][0]
    assert account["state"] == "unavailable" and "user_code" not in account and "flow_id" not in account


def test_authorization_callback_failure_is_sanitized():
    app = FastAPI()
    def failure(_request):
        raise RuntimeError("private authorization detail")
    app.include_router(routes.create_platform_accounts_router(Account(), failure))
    client = TestClient(app, base_url=ORIGIN, client=("127.0.0.1", 1234))
    reply = client.get(PATH)
    assert reply.status_code == 503 and reply.json()["reason"] == "account_unavailable"


class YouTube(Account):
    def __init__(self):
        super().__init__()
        self.value['platform'] = 'youtube'
        self.flow = None
        self.url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
            'client_id': 'synthetic.apps.googleusercontent.com', 'redirect_uri': 'http://127.0.0.1:8778/callback',
            'response_type': 'code', 'scope': 'https://www.googleapis.com/auth/youtube.readonly',
            'access_type': 'offline', 'prompt': 'consent', 'state': 'private-state',
            'code_challenge': 'synthetic-public-challenge', 'code_challenge_method': 'S256'})

    async def begin(self):
        self.begins += 1
        self.flow = 'e' * 32
        self.value.update(state='pending', reason='authorization_pending', flow_id=self.flow,
                          expires_at=1795060000.5, authorization_url=self.url, client_secret='private-secret')

    async def cancel(self):
        await super().cancel()
        self.flow = None

    def authorization_url(self, flow):
        return self.url if flow == self.flow else None


def test_youtube_flow_url_is_separate_from_status_and_cancel_preserves_vault():
    youtube, audit = YouTube(), []
    _, vault, _, client = fixture(youtube=youtube, audit=lambda **event: audit.append(event))
    assert client.get(PATH).json()['accounts'][1]['app_configured'] is True and youtube.begins == 0
    before = json.dumps(vault.records)
    reply = client.post(PATH + '/youtube/begin', json={}, headers={'Origin': ORIGIN})
    assert reply.status_code == 200 and reply.json()['account']['flow_id'] == 'e' * 32
    assert 'authorization_url' not in reply.text and 'private-' not in reply.text
    assert 'authorization_url' not in client.get(PATH).text
    url = client.get(PATH + '/youtube/authorization', params={'flow_id': 'e' * 32})
    assert url.status_code == 200 and url.json() == {'authorization_url': youtube.url}
    assert url.headers['cache-control'] == 'no-store'
    assert client.get(PATH + '/youtube/authorization', params={'flow_id': 'a' * 32}).status_code == 409
    assert client.post(PATH + '/youtube/cancel', json={}, headers={'Origin': ORIGIN}).status_code == 200
    assert client.get(PATH + '/youtube/authorization', params={'flow_id': 'e' * 32}).status_code == 409
    assert json.dumps(vault.records) == before
    assert audit == [{'action': 'youtube.begin', 'outcome': 'requested'}, {'action': 'youtube.begin', 'outcome': 'pending'}, {'action': 'youtube.cancel', 'outcome': 'requested'}, {'action': 'youtube.cancel', 'outcome': 'not_authorized'}]


@pytest.mark.parametrize('options', [{'host': '198.51.100.7'}, {'origin': 'http://rebind.example:8765'}, {'authorized': False}])
def test_youtube_routes_preserve_local_operator_guards(options):
    youtube = YouTube()
    _, _, _, client = fixture(youtube=youtube, **options)
    for action in ('begin', 'cancel'):
        assert client.post(PATH + '/youtube/' + action, json={}, headers={'Origin': ORIGIN}).status_code == 403
    assert client.get(PATH + '/youtube/authorization', params={'flow_id': 'e' * 32}).status_code == 403
    assert youtube.begins == youtube.cancels == 0


@pytest.mark.parametrize('mutation', ['host', 'scheme', 'path', 'redirect', 'secret', 'duplicate'])
def test_youtube_authorization_url_rejects_wrong_endpoint_redirect_or_secret_parameters(mutation):
    youtube = YouTube()
    youtube.flow = 'e' * 32
    if mutation == 'host':
        youtube.url = youtube.url.replace('accounts.google.com', 'untrusted.example', 1)
    elif mutation == 'scheme':
        youtube.url = youtube.url.replace('https://', 'http://', 1)
    elif mutation == 'path':
        youtube.url = youtube.url.replace('/o/oauth2/v2/auth?', '/other?')
    elif mutation == 'redirect':
        youtube.url = youtube.url.replace('127.0.0.1', 'outside.example')
    elif mutation == 'secret':
        youtube.url += '&access_token=private-token'
    else:
        youtube.url += '&redirect_uri=http%3A%2F%2F127.0.0.1%3A8778%2Fcallback'
    _, _, _, client = fixture(youtube=youtube)
    reply = client.get(PATH + '/youtube/authorization', params={'flow_id': 'e' * 32})
    assert reply.status_code == 503 and reply.json() == {'ok': False, 'reason': 'account_unavailable'}


def test_youtube_url_endpoint_rejects_cross_origin_and_malformed_flow_query():
    youtube = YouTube()
    _, _, _, client = fixture(youtube=youtube)
    assert client.get(PATH + '/youtube/authorization', params={'flow_id': 'e' * 32}, headers={'Origin': 'https://outside.example'}).status_code == 403
    for query in ['', '?flow_id=wrong', '?flow_id=' + 'e' * 32 + '&flow_id=' + 'e' * 32]:
        assert client.get(PATH + '/youtube/authorization' + query).status_code == 400
    assert client.post(PATH + '/youtube/begin', json={'client_secret': 'private'}, headers={'Origin': ORIGIN}).status_code == 400
    assert youtube.begins == 0
