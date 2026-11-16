"""Provider HTTP and signed deliveries are local fixtures; no credentials/network used."""
import asyncio
import base64
from datetime import datetime, timezone
import json

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import FastAPI
import httpx
import pytest

from rareiq.services.audience_service import AudienceService
from rareiq.services.kick_audience_connector import KickAudienceConnector, KickWebhookRegistration
from rareiq.web.kick_audience import create_kick_audience_router

NOW = 1800000000.0
APP, SUB, DELIVERY = "0" + "2" * 25, "0" + "3" * 25, "0" + "1" * 25
URL = "https://studio.example.com/integrations/kick/events"


class Fixture:
    def __init__(self, tmp_path, approved=True):
        self.now, self.calls, self.credential_reads = NOW, [], 0
        self.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.key = self.private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        self.auth = {"active": True, "token_type": "user", "client_id": APP, "exp": NOW + 7200, "scope": "user:read channel:read events:subscribe"}
        self.users = [{"user_id": 123}]
        self.channels = [{"slug": "fixture-channel", "broadcaster_user_id": 123}]
        self.subscriptions = [{"id": SUB, "app_id": APP, "broadcaster_user_id": 123, "method": "webhook", "event": "chat.message.sent", "version": 1}]
        self.provider_status = 200
        self.audience = AudienceService(tmp_path / "audience.sqlite3", clock=lambda: self.now)
        self.audience.status()
        self.audience.configure(action="save_rule", data={"id": "welcome", "name": "Welcome", "enabled": True, "platform": "kick", "event": "first_chat", "message": "Hello {name}", "animation": "slide", "duration_ms": 3000, "cooldown_seconds": 60}, expected_revision=0, request_id="rule", actor_kind="local_operator")
        self.audience.configure(action="settings", data={"enabled": True}, expected_revision=1, request_id="enabled", actor_kind="local_operator")
        self.service = KickAudienceConnector(self.audience, self.credentials,
            KickWebhookRegistration(URL, APP, SUB, approved), clock=lambda: self.now,
            http_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(self.http)))

    def credentials(self):
        self.credential_reads += 1
        return {"client_id": APP, "channel_slug": "fixture-channel", "user_access_token": "fixture-private-token"}

    def http(self, request):
        endpoint = request.url.path.removeprefix("/public/v1/")
        self.calls.append((request.method, endpoint))
        if self.provider_status != 200:
            return httpx.Response(self.provider_status, text="private-provider-response")
        data = {"token/introspect": self.auth, "users": self.users, "channels": self.channels,
                "events/subscriptions": self.subscriptions, "public-key": {"public_key": self.key}}[endpoint]
        return httpx.Response(200, json={"data": data})

    def delivery(self, *, message_id=DELIVERY, private=None, **changes):
        timestamp = datetime.fromtimestamp(self.now, timezone.utc).isoformat().replace("+00:00", "Z")
        payload = {"message_id": "chat-one", "broadcaster": {"is_anonymous": False, "user_id": 123, "channel_slug": "fixture-channel"},
                   "sender": {"is_anonymous": False, "user_id": 456, "username": "Fixture viewer"}, "content": "PRIVATE-CHAT-NOT-PERSISTED", "created_at": timestamp}
        payload.update(changes)
        raw = json.dumps(payload).encode()
        signature = (private or self.private).sign(message_id.encode() + b"." + timestamp.encode() + b"." + raw, padding.PKCS1v15(), hashes.SHA256())
        return {"kick-event-message-id": message_id, "kick-event-subscription-id": SUB,
                "kick-event-signature": base64.b64encode(signature).decode(), "kick-event-message-timestamp": timestamp,
                "kick-event-type": "chat.message.sent", "kick-event-version": "1"}, raw


def test_unapproved_registration_does_not_read_credentials_or_make_requests(tmp_path):
    async def run():
        f = Fixture(tmp_path, approved=False)
        assert not f.service.cached_status()["connected"]
        assert (await f.service.connect())["reason"] == "dashboard_registration_approval_required"
        assert f.credential_reads == 0 and f.calls == []
        assert (await f.service.receive({}, b"{}"))[1] == 503
    asyncio.run(run())


def test_failed_expired_key_refresh_cannot_reauthorize_cached_old_key(tmp_path):
    async def run():
        f = Fixture(tmp_path)
        await f.service.connect()
        f.now += 301
        f.provider_status = 503
        headers, raw = f.delivery()
        result, code = await f.service.receive(headers, raw)
        assert code == 503 and result["reason"] == "provider_key_unavailable"
        assert f.service._key is None and f.service._key_at == 0
        # A retry signed with the old key must not enter the audience queue.
        f.provider_status = 200
        assert (await f.service.receive(headers, raw))[1] == 503
        assert not f.service.cached_status()["connected"]
        assert f.audience.status()["participants"] == []
        await f.service.disconnect()
    asyncio.run(run())


def test_valid_signature_routes_chat_without_content_or_credentials_in_storage(tmp_path):
    async def run():
        f = Fixture(tmp_path)
        assert (await f.service.connect())["state"] == "ready"
        assert not f.service.cached_status()["verified"]  # Token evidence is not a webhook receipt.
        headers, raw = f.delivery()
        result, code = await f.service.receive(headers, raw)
        assert code == 200 and result["queued"] == 1
        assert (await f.service.receive(headers, raw))[0]["duplicate"]
        assert f.service.cached_status()["verified"] and f.service.cached_status()["state"] == "connected"
        assert f.audience.output()["graphic"]["title"] == "Hello Fixture viewer"
        stored = f.audience.path.read_bytes()
        assert b"PRIVATE-CHAT" not in stored and b"fixture-private-token" not in stored
        assert "Fixture viewer" not in json.dumps(f.service.cached_status())
        assert all(method == "GET" or endpoint == "token/introspect" for method, endpoint in f.calls)
        await f.service.disconnect()
        assert (await f.service.receive(headers, raw))[1] == 503
    asyncio.run(run())


@pytest.mark.parametrize("reason", ["audience_event_capacity", "audience_event_outside_session", "private-exception"])
def test_signed_event_rejected_by_audience_is_not_reported_as_success(tmp_path, reason):
    async def run():
        f = Fixture(tmp_path)
        await f.service.connect()
        f.audience.accept = lambda event: {"ok": False, "reason": reason}
        result, code = await f.service.receive(*f.delivery())
        assert code == 409 and result["ok"] is False and result["queued"] == 0
        assert result["reason"] == (reason if reason != "private-exception" else "audience_intake_rejected")
        status = f.service.cached_status()
        assert status["received"] == 0 and status["rejected"] == 1
        assert not status["connected"] and not f.service._seen
        await f.service.disconnect()
    asyncio.run(run())


@pytest.mark.parametrize("change", ["scope", "active", "client", "expiry", "nan_expiry", "app_token", "channel", "subscription", "app", "version", "provider_failure"])
def test_ownership_scope_and_subscription_fail_closed(tmp_path, change):
    async def run():
        f = Fixture(tmp_path)
        if change == "scope": f.auth["scope"] = "user:read channel:read"
        if change == "active": f.auth["active"] = False
        if change == "client": f.auth["client_id"] = "wrong"
        if change == "expiry": f.auth["exp"] = NOW + 20
        if change == "nan_expiry": f.auth["exp"] = "NaN"
        if change == "app_token": f.auth["token_type"] = "app"
        if change == "channel": f.channels[0]["broadcaster_user_id"] = 999
        if change == "subscription": f.subscriptions[0]["id"] = "wrong"
        if change == "app": f.subscriptions[0]["app_id"] = "wrong"
        if change == "version": f.subscriptions[0]["version"] = 2
        if change == "provider_failure": f.provider_status = 403
        status = await f.service.connect()
        assert not status["authorized"] and not status["connected"] and not f.service.accepts_url(URL)
        assert "private" not in json.dumps(status)
    asyncio.run(run())


@pytest.mark.parametrize("change", ["body", "signature", "subscription", "type", "version", "stale", "future", "anonymous", "channel", "chat_id", "name", "oversize"])
def test_bad_signed_or_unbound_deliveries_never_reach_audience(tmp_path, change):
    async def run():
        f = Fixture(tmp_path); await f.service.connect()
        if change == "anonymous": headers, raw = f.delivery(sender={"is_anonymous": True, "user_id": 456, "username": "Fixture viewer"})
        elif change == "channel": headers, raw = f.delivery(broadcaster={"is_anonymous": False, "user_id": 999, "channel_slug": "fixture-channel"})
        elif change == "chat_id": headers, raw = f.delivery(message_id="0" + "4" * 25, **{"content": "x", "sender": {"is_anonymous": False, "user_id": True, "username": "Viewer"}})
        elif change == "name": headers, raw = f.delivery(sender={"is_anonymous": False, "user_id": 456, "username": "bad\nname"})
        else: headers, raw = f.delivery()
        if change == "body": raw += b" "
        if change == "signature": headers["kick-event-signature"] = "not-base64"
        if change == "subscription": headers["kick-event-subscription-id"] = "wrong"
        if change == "type": headers["kick-event-type"] = "channel.followed"
        if change == "version": headers["kick-event-version"] = "2"
        if change == "stale": f.now += 121
        if change == "future": f.now -= 6
        if change == "oversize": raw = b"x" * 65537
        assert (await f.service.receive(headers, raw))[1] == 400
        assert f.service.cached_status()["received"] == 0
        assert f.audience.output()["graphic"] is None
        await f.service.disconnect()
    asyncio.run(run())


def test_rotation_revalidation_and_replay_conflict(tmp_path):
    async def run():
        f = Fixture(tmp_path); await f.service.connect()
        headers, raw = f.delivery(); assert (await f.service.receive(headers, raw))[1] == 200
        changed = f.delivery(content="different")
        assert (await f.service.receive(*changed))[0]["reason"] == "event_id_conflict"
        f.now += 31
        f.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        f.key = f.private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        assert (await f.service.receive(*f.delivery(message_id="0" + "4" * 25)))[1] == 200
        assert f.calls.count(("GET", "public-key")) == 2
        f.now += 31; f.auth["active"] = False
        assert (await f.service.receive(*f.delivery(message_id="0" + "5" * 25)))[1] == 503
        assert not f.service.cached_status()["authorized"]
    asyncio.run(run())


def test_second_delivery_of_same_chat_deduplicates_durably_and_featured_chat_uses_existing_rules(tmp_path):
    async def run():
        f = Fixture(tmp_path);await f.service.connect()
        first = await f.service.receive(*f.delivery())
        assert first[0]["queued"] == 1
        assert (await f.service.receive(*f.delivery(message_id="0" + "4" * 25)))[0]["duplicate"]
        f.audience.configure(action="feature", data={"platform": "kick", "channel_id": "123", "subject_id": "456", "label": "Featured viewer"}, expected_revision=2, request_id="feature", actor_kind="local_operator")
        f.audience.configure(action="save_rule", data={"id": "featured", "name": "Featured", "enabled": True, "platform": "kick", "event": "featured_chat", "message": "Welcome back {name}", "animation": "spotlight", "duration_ms": 3000, "cooldown_seconds": 60}, expected_revision=3, request_id="featured-rule", actor_kind="local_operator")
        headers, raw = f.delivery(message_id="0" + "5" * 25)
        payload = json.loads(raw);payload["message_id"] = "chat-two";raw = json.dumps(payload).encode()
        signed = headers["kick-event-message-id"].encode()+b"."+headers["kick-event-message-timestamp"].encode()+b"."+raw
        headers["kick-event-signature"] = base64.b64encode(f.private.sign(signed, padding.PKCS1v15(), hashes.SHA256())).decode()
        assert (await f.service.receive(headers, raw))[0]["queued"] == 1
        f.now += 3.1
        assert f.audience.output()["graphic"]["subtitle"] == "Featured participant"
        await f.service.disconnect()
    asyncio.run(run())


def test_invalid_signature_flood_is_bounded_and_never_refreshes_key_repeatedly(tmp_path):
    async def run():
        f = Fixture(tmp_path);await f.service.connect();f.now += 31
        headers, raw = f.delivery();headers["kick-event-signature"] = base64.b64encode(b"x"*256).decode()
        for _ in range(120): assert (await f.service.receive(headers, raw))[1] == 400
        assert (await f.service.receive(headers, raw))[1] == 429
        assert f.calls.count(("GET", "public-key")) == 2
        assert f.audience.output()["graphic"] is None
        await f.service.disconnect()
    asyncio.run(run())


def test_router_exact_url_duplicate_headers_body_limit_and_local_controls(tmp_path):
    async def run():
        f = Fixture(tmp_path); app = FastAPI(); app.include_router(create_kick_audience_router(f.service, lambda request: True, include_receiver=True))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app, client=("127.0.0.1", 3000)), base_url="http://127.0.0.1") as local:
            assert (await local.post("/api/production/audience/kick/connect", json={})).status_code == 403
            assert (await local.post("/api/production/audience/kick/connect", json={}, headers={"Origin": "http://127.0.0.1"})).json()["state"] == "ready"
        headers, raw = f.delivery(); headers["content-type"] = "application/json"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app, client=("198.51.100.10", 3000)), base_url="https://studio.example.com") as remote:
            assert (await remote.get("/api/production/audience/kick")).status_code == 403
            assert (await remote.post(f.service.CALLBACK_PATH, content=raw, headers=headers)).status_code == 200
            assert (await remote.post(f.service.CALLBACK_PATH + "?other=1", content=raw, headers=headers)).status_code == 503
            assert (await remote.post(f.service.CALLBACK_PATH, content=raw, headers=list(headers.items()) + [("kick-event-type", "chat.message.sent")])).status_code == 400
            assert (await remote.post(f.service.CALLBACK_PATH, content=b"x"*65537, headers=headers)).status_code == 413
        await f.service.disconnect()
    asyncio.run(run())


def test_receiver_unmounted_by_default_and_stale_authorization_cannot_claim_connected(tmp_path):
    async def run():
        f = Fixture(tmp_path);app = FastAPI();app.include_router(create_kick_audience_router(f.service, lambda request: True))
        assert f.service.CALLBACK_PATH not in [route.path for route in app.routes]
        await f.service.connect();await f.service.receive(*f.delivery())
        f.now += 60
        assert not f.service.cached_status()["authorized"] and not f.service.cached_status()["connected"]
        assert f.service.cached_status()["reason"] == "authorization_refresh_required"
        assert (await f.service.connect())["state"] == "connected"
        f.now += 121
        assert (await f.service.connect())["state"] == "ready"
        await f.service.disconnect()
    asyncio.run(run())


@pytest.mark.parametrize("url", ["http://studio.example.com/integrations/kick/events", "https://localhost/integrations/kick/events", "https://127.0.0.1/integrations/kick/events", URL+"?token=secret", URL+"#fragment", "https://user:password@studio.example.com/integrations/kick/events", "https://studio.example.com/other"])
def test_callback_requires_exact_approved_https_surface(tmp_path, url):
    async def run():
        f = Fixture(tmp_path);f.service._registration = KickWebhookRegistration(url, APP, SUB, True)
        assert (await f.service.connect())["reason"] == "approved_https_callback_required"
        assert not f.calls
    asyncio.run(run())
