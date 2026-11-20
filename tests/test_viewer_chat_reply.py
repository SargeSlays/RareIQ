"""Reply sending uses only synthetic accounts and mock HTTP; never a real post."""
import asyncio
import json
from types import SimpleNamespace

from fastapi import FastAPI
import httpx
import pytest

from rareiq.services.viewer_chat_reply_service import ViewerChatReplyService, AccountChatReplyAdapter
from rareiq.web.viewer_chat_reply import create_viewer_chat_reply_router
from rareiq.services.twitch_account_service import TwitchAccountService
from rareiq.services.youtube_account_service import YouTubeAccountService
from rareiq.services.kick_account_service import KickAccountService


class Account:
    def __init__(self, platform, *, scope=True):
        self.platform = platform
        self.record = dict(channel_id="UC" + "a" * 22 if platform == "youtube" else "123",
            access_token="synthetic-private-access", client_id="synthetic-client",
            scopes=[AccountChatReplyAdapter.SCOPES[platform]] if scope else [])
        self.reference = "a" * 64

    def cached_chat_reply_context(self):
        return dict(authorized=True, channel_id=self.record["channel_id"], account_ref=self.reference,
                    scopes=tuple(self.record["scopes"]))

    async def with_chat_reply_access(self, operation):
        if AccountChatReplyAdapter.SCOPES[self.platform] not in self.record["scopes"]:
            raise ValueError("chat_send_permission_required")
        return await operation(self.record, lambda: None)


def rig(tmp_path, handler=None, *, scopes=True, audit=None):
    accounts = {platform: Account(platform, scope=scopes) for platform in ("twitch", "youtube", "kick")}
    targets = {platform: dict(channel_id=account.record["channel_id"], **({"live_chat_id": "synthetic-live-chat"} if platform == "youtube" else {})) for platform, account in accounts.items()}
    connectors = {platform: SimpleNamespace(cached_chat_reply_target=lambda key=platform: targets[key]) for platform in accounts}
    calls = []

    def transport(request):
        calls.append(request)
        if handler:
            value = handler(request, calls)
            if value is not None:
                return value
        if request.url.host == "www.googleapis.com":
            return httpx.Response(200, json={"id": "synthetic-youtube-reply", "snippet": {"liveChatId": "synthetic-live-chat"}})
        payload = {"message_id": "synthetic-reply", "is_sent": True}
        return httpx.Response(200, json={"data": [payload] if request.url.host == "api.twitch.tv" else payload})

    factory = lambda: httpx.AsyncClient(transport=httpx.MockTransport(transport), trust_env=False)
    service = ViewerChatReplyService(accounts, connectors, receipt_path=tmp_path / "reply.sqlite3", http_factory=factory, audit=audit)
    return service, accounts, targets, calls, factory


def payload(**extra):
    return {"request_id": "stable-reply", "text": "Literal <b>reply</b> 🎥", "targets": ["twitch", "youtube", "kick"], **extra}


def test_all_fanout_exact_retry_durable_restart_and_private_projection(tmp_path):
    async def run():
        service, accounts, targets, calls, factory = rig(tmp_path)
        assert all(target["ready"] for target in service.status()["targets"])
        result = await service.reply(payload())
        assert [row["state"] for row in result["results"]] == ["sent"] * 3
        assert len(calls) == 3
        duplicate = await service.reply(payload())
        assert duplicate["duplicate"] and len(calls) == 3
        restarted = ViewerChatReplyService(receipt_path=tmp_path / "reply.sqlite3", adapters=service._adapters)
        assert (await restarted.reply(payload()))["duplicate"] and len(calls) == 3
        assert "synthetic-private-access" not in json.dumps(result)
        assert payload()["text"].encode() not in (tmp_path / "reply.sqlite3").read_bytes()
        assert b"synthetic-private-access" not in (tmp_path / "reply.sqlite3").read_bytes()
        twitch, youtube, kick = [json.loads(request.content) for request in calls]
        assert twitch == {"broadcaster_id": "123", "sender_id": "123", "message": payload()["text"]}
        assert youtube["snippet"]["liveChatId"] == "synthetic-live-chat"
        assert kick == {"broadcaster_user_id": 123, "content": payload()["text"], "type": "user"}
        assert [str(request.url) for request in calls] == ["https://api.twitch.tv/helix/chat/messages", "https://www.googleapis.com/youtube/v3/liveChat/messages?part=snippet", "https://api.kick.com/public/v1/chat"]
    asyncio.run(run())


def test_partial_results_retry_only_known_rate_limited_never_sent_or_uncertain(tmp_path):
    async def run():
        counts = {"api.twitch.tv": 0, "www.googleapis.com": 0, "api.kick.com": 0}
        def handler(request, calls):
            counts[request.url.host] += 1
            if request.url.host == "www.googleapis.com" and counts[request.url.host] == 1:
                return httpx.Response(429)
            if request.url.host == "api.kick.com":
                raise httpx.ReadTimeout("synthetic-private-access", request=request)
        service, _, _, calls, _ = rig(tmp_path, handler)
        result = await service.reply(payload())
        assert [row["state"] for row in result["results"]] == ["sent", "failed", "uncertain"]
        assert [row["retryable"] for row in result["results"]] == [False, True, False]
        result = await service.reply(payload(retry_failed=True))
        assert [row["state"] for row in result["results"]] == ["sent", "sent", "uncertain"]
        assert counts == {"api.twitch.tv": 1, "www.googleapis.com": 2, "api.kick.com": 1}
    asyncio.run(run())


def test_pending_crash_receipt_is_uncertain_and_cannot_retry(tmp_path):
    async def run():
        service, _, _, calls, _ = rig(tmp_path)
        entered, release = asyncio.Event(), asyncio.Event()
        original = service._adapters["twitch"].send
        async def delayed(text, binding):
            entered.set()
            await release.wait()
            return await original(text, binding)
        service._adapters["twitch"].send = delayed
        task = asyncio.create_task(service.reply(payload(targets=["twitch"])))
        await entered.wait()
        restarted = ViewerChatReplyService(receipt_path=tmp_path / "reply.sqlite3", adapters=service._adapters)
        recovery = await restarted.reply(payload(targets=["twitch"], retry_failed=True))
        assert recovery["results"][0]["state"] == "uncertain" and not recovery["results"][0]["retryable"]
        assert calls == []
        release.set()
        assert (await task)["results"][0]["state"] == "sent"
        assert len(calls) == 1
    asyncio.run(run())


@pytest.mark.parametrize("change", [{"text": ""}, {"text": "x" * 201}, {"text": "bad\nline"}, {"text": "bad\x85"}, {"text": "\ud800"}, {"targets": []}, {"targets": ["twitch"] * 2}, {"targets": ["other"]}, {"targets": "all"}, {"request_id": "bad\n"}, {"request_id": "x" * 81}, {"retry_failed": 1}, {"token": "forbidden"}])
def test_invalid_input_never_contacts_provider(tmp_path, change):
    service, _, _, calls, _ = rig(tmp_path)
    with pytest.raises(ValueError, match="invalid_chat_reply"):
        asyncio.run(service.reply(payload(**change)))
    assert not calls


def test_read_only_scopes_disconnected_targets_and_payload_conflicts_fail_closed(tmp_path):
    async def run():
        service, accounts, targets, calls, _ = rig(tmp_path, scopes=False)
        assert {row["reason"] for row in service.status()["targets"]} == {"chat_send_permission_required"}
        result = await service.reply(payload())
        assert {row["reason"] for row in result["results"]} == {"chat_send_permission_required"}
        assert not calls
        with pytest.raises(ValueError, match="chat_request_conflict"):
            await service.reply(payload(text="Different text"))
        accounts["twitch"].record["scopes"] = ["user:write:chat"]
        targets["twitch"] = None
        assert service.status()["targets"][0] == {"platform": "twitch", "ready": False, "reason": "chat_not_connected"}
    asyncio.run(run())


def test_target_change_and_audit_failure_prevent_provider_writes(tmp_path):
    async def run():
        def handler(request, calls):
            return httpx.Response(429)
        service, accounts, targets, calls, _ = rig(tmp_path, handler)
        await service.reply(payload(targets=["twitch"]))
        accounts["twitch"].record["channel_id"] = targets["twitch"]["channel_id"] = "456"
        result = await service.reply(payload(targets=["twitch"], retry_failed=True))
        assert result["results"][0]["reason"] == "chat_target_changed" and len(calls) == 1
        service._audit = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("private audit error"))
        result = await service.reply(payload(request_id="audit", targets=["twitch"]))
        assert result["results"][0]["reason"] == "chat_activity_unavailable" and len(calls) == 1
    asyncio.run(run())


def test_router_loopback_origin_bounds_rehearsal_and_literal_reply(tmp_path):
    async def run():
        service, _, _, calls, _ = rig(tmp_path)
        app = FastAPI()
        allowed = [True]
        app.include_router(create_viewer_chat_reply_router(service, lambda request: True, can_send=lambda: allowed[0]))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 1)), base_url="http://127.0.0.1:8765") as client:
            assert (await client.get("/api/production/viewer-chat/reply-status")).json()["max_length"] == 200
            assert (await client.post("/api/production/viewer-chat/reply", json=payload())).status_code == 403
            headers = {"Origin": "http://127.0.0.1:8765", "Content-Type": "application/json"}
            allowed[0] = False
            assert not any(row["ready"] for row in (await client.get("/api/production/viewer-chat/reply-status")).json()["targets"])
            assert (await client.post("/api/production/viewer-chat/reply", headers=headers, json=payload())).status_code == 409
            assert not calls
            allowed[0] = True
            for body in ['{"request_id":"a","request_id":"b"}', "x" * 2049]:
                assert (await client.post("/api/production/viewer-chat/reply", headers=headers, content=body)).status_code == 400
            result = await client.post("/api/production/viewer-chat/reply", headers=headers, json=payload(targets=["twitch"]))
            assert result.status_code == 200 and result.json()["results"][0]["state"] == "sent"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("192.0.2.1", 1)), base_url="http://127.0.0.1:8765") as remote:
            assert (await remote.get("/api/production/viewer-chat/reply-status")).status_code == 403
    asyncio.run(run())


@pytest.mark.parametrize("owner_class,scope", [(TwitchAccountService, "user:write:chat"),
    (YouTubeAccountService, "https://www.googleapis.com/auth/youtube.force-ssl"), (KickAccountService, "chat:write")])
def test_account_owned_reply_access_requires_send_scope_without_unrelated_metadata_gate(owner_class, scope):
    async def run():
        owner = object.__new__(owner_class)
        record = dict(channel_id="123", scopes=[], access_token="private-synthetic-token")
        owner.status = lambda: {"authorized": True, "account_ref": "a" * 64}
        owner._stored = lambda: record
        calls = []
        async def access(operation, *, require_edit):
            calls.append(require_edit)
            return await operation(record, lambda: None)
        owner.with_stream_info_access = access
        cached = owner.cached_chat_reply_context()
        assert "access_token" not in cached and cached["scopes"] == ()
        async def operation(value, guard):
            guard()
            assert value is record
            return "sent-with-private-owner"
        with pytest.raises(Exception, match="chat_send_permission_required"):
            await owner.with_chat_reply_access(operation)
        record["scopes"] = [scope]
        assert await owner.with_chat_reply_access(operation) == "sent-with-private-owner"
        assert calls == [False, False]
    asyncio.run(run())


@pytest.mark.parametrize("response,state,reason", [
    (httpx.Response(500), "uncertain", "chat_send_uncertain"),
    (httpx.Response(200, content=b"not json"), "uncertain", "chat_send_uncertain"),
    (httpx.Response(200, content=b"x" * 65537), "uncertain", "chat_send_uncertain"),
    (httpx.Response(403), "failed", "chat_send_permission_required"),
    (httpx.Response(400), "failed", "chat_provider_rejected"),
    (httpx.Response(200, json={"data": [{"is_sent": False}]}), "failed", "chat_provider_rejected"),
])
def test_provider_ambiguity_is_never_retryable_and_explicit_rejections_are_not_sent(tmp_path, response, state, reason):
    service, _, _, calls, _ = rig(tmp_path, lambda request, calls: response)
    result = asyncio.run(service.reply(payload(targets=["twitch"])))
    assert result["results"] == [dict(platform="twitch", state=state, reason=reason, retryable=False)]
    assert len(calls) == 1


def test_durable_capacity_never_evicts_sent_receipts_or_enables_duplicate_reuse(tmp_path):
    async def run():
        service, _, _, calls, _ = rig(tmp_path)
        service._store.MAX_RECEIPTS = 1
        await service.reply(payload(targets=["twitch"]))
        with pytest.raises(ValueError, match="chat_receipt_capacity"):
            await service.reply(payload(request_id="new-id", targets=["twitch"]))
        assert (await service.reply(payload(targets=["twitch"])))['duplicate']
        assert len(calls) == 1
        broken = ViewerChatReplyService(receipt_path=tmp_path, adapters=service._adapters)
        assert {row["reason"] for row in broken.status()["targets"]} == {"chat_storage_unavailable"}
        with pytest.raises(ValueError, match="chat_storage_unavailable"):
            await broken.reply(payload(targets=["twitch"]))
    asyncio.run(run())
