"""Isolated desktop-account HTTP fixture; no provider or real credential access."""
import asyncio
from copy import deepcopy
import json
import time

from fastapi import Request
from fastapi.responses import JSONResponse
import httpx

from qa_greenroom_fixture import main
from qa_viewer_chat_fixture import setup as chat_setup
from rareiq.services.stream_metadata_service import StreamMetadataService
from rareiq.core.stream_metadata_receipts import StreamMetadataReceiptStore


def metadata_setup(server, root):
    """Keep the original router/service, substituting private owners and HTTP only."""
    metadata = server.stream_metadata_service
    metadata._receipt_store = StreamMetadataReceiptStore(root / 'stream-metadata-receipts.json')
    metadata._receipt_error = None
    metadata._receipts.clear()
    state = {"mode": "normal", "settling": False, "calls": [], "owners": [],
             "fields": {platform: {"title": "Synthetic original title", "category_id": "42",
                                   "tags": ["Original"], "description": "Synthetic original description"}
                        for platform in ("twitch", "youtube", "kick")}}

    class Owner:
        def __init__(self, platform):
            self.platform, self.lock = platform, asyncio.Lock()
            self.record = {"access_token": "synthetic-metadata-private-access-token",
                           "client_id": "synthetic-metadata-private-app", "public_label": "fixture_channel",
                           "channel_id": "UCsynthetic_owned_channel" if platform == "youtube" else "123",
                           "scopes": [StreamMetadataService.EDIT_SCOPES[platform]]}

        async def with_stream_info_access(self, operation, *, require_edit=False):
            async with self.lock:
                state["owners"].append({"platform": self.platform, "edit": require_edit})
                active = True
                def guard():
                    if not active or not self.lock.locked():
                        raise ValueError("account_state_changed")
                try:
                    return await operation(deepcopy(self.record), guard)
                finally:
                    active = False

    owners = {platform: Owner(platform) for platform in state["fields"]}

    async def provider(request):
        endpoints = {
            metadata.TWITCH_CHANNELS: "twitch", metadata.TWITCH_SEARCH: "twitch", metadata.TWITCH_GAMES: "twitch",
            metadata.KICK_CHANNELS: "kick", metadata.KICK_CATEGORIES: "kick",
            metadata.YOUTUBE_BROADCASTS: "youtube", metadata.YOUTUBE_VIDEOS: "youtube",
            metadata.YOUTUBE_CATEGORIES: "youtube"}
        endpoint = str(request.url.copy_with(query=None))
        platform = endpoints.get(endpoint)
        if platform is None or request.url.scheme != "https":
            raise AssertionError("Unexpected synthetic provider endpoint")
        if request.headers.get("Authorization") != "Bearer synthetic-metadata-private-access-token":
            raise AssertionError("Synthetic private authorization required")
        body = json.loads(request.content) if request.content else None
        # Retain public metadata only. Headers/private records are never evidence.
        state["calls"].append({"method": request.method, "platform": platform,
                               "path": request.url.path, "body": deepcopy(body)})
        fields = state["fields"][platform]
        if request.method in {"PATCH", "PUT"}:
            expected = "PUT" if platform == "youtube" else "PATCH"
            if request.method != expected:
                raise AssertionError("Unsupported synthetic mutation")
            if platform == "youtube":
                if endpoint != metadata.YOUTUBE_VIDEOS or request.url.params.get("part") != "snippet" or request.headers.get("If-Match") != '"synthetic-fresh-etag"':
                    raise AssertionError("Guarded snippet update required")
                source = body["snippet"]
                fields.update(title=source["title"], category_id=source["categoryId"],
                              description=source.get("description", ""), tags=source.get("tags", []))
            else:
                channel_endpoint = metadata.TWITCH_CHANNELS if platform == "twitch" else metadata.KICK_CHANNELS
                if endpoint != channel_endpoint:
                    raise AssertionError("Metadata channel update required")
                for key, provider_key in (("title", "title" if platform == "twitch" else "stream_title"),
                                          ("category_id", "game_id" if platform == "twitch" else "category_id"),
                                          ("tags", "tags" if platform == "twitch" else "custom_tags")):
                    if provider_key in body:
                        fields[key] = str(body[provider_key]) if key == "category_id" else body[provider_key]
            if state["mode"] == "uncertain":
                state["settling"] = True
                raise httpx.ReadTimeout("Synthetic uncertain response")
            return httpx.Response(200, json={"id": "fixture-broadcast"}) if platform == "youtube" else httpx.Response(204)
        if request.method != "GET":
            raise AssertionError("Unsupported synthetic request")
        if state["settling"]:
            raise httpx.ReadTimeout("Synthetic delayed readback")
        if endpoint in {metadata.TWITCH_SEARCH, metadata.TWITCH_GAMES, metadata.KICK_CATEGORIES}:
            return httpx.Response(200, json={"data": [{"id": 42 if platform == "kick" else "42", "name": "Synthetic Science"}]})
        if endpoint == metadata.YOUTUBE_CATEGORIES:
            return httpx.Response(200, json={"items": [{"id": "42", "snippet": {"title": "Synthetic Science", "assignable": True}}]})
        if endpoint == metadata.YOUTUBE_BROADCASTS:
            selected = request.url.params.get("id")
            items = [] if selected and selected != "fixture-broadcast" else [{"id": "fixture-broadcast",
                "snippet": {"channelId": owners[platform].record["channel_id"], "title": fields["title"]},
                "status": {"lifeCycleStatus": "ready"}}]
            return httpx.Response(200, json={"items": items})
        if endpoint == metadata.YOUTUBE_VIDEOS:
            return httpx.Response(200, json={"items": [{"id": "fixture-broadcast", "etag": '"synthetic-fresh-etag"',
                "snippet": {"channelId": owners[platform].record["channel_id"], "title": fields["title"],
                            "description": fields["description"], "categoryId": fields["category_id"],
                            "tags": fields["tags"], "defaultLanguage": "en"}}]})
        if platform == "twitch":
            value = {"broadcaster_id": "123", "title": fields["title"], "game_id": fields["category_id"],
                     "game_name": "Synthetic Science", "tags": fields["tags"]}
        else:
            value = {"broadcaster_user_id": 123, "stream_title": fields["title"],
                     "category": {"id": int(fields["category_id"]), "name": "Synthetic Science"},
                     "stream": {"custom_tags": fields["tags"], "key": "synthetic-private-stream-key"}}
        return httpx.Response(200, json={"data": [value]})

    metadata._accounts = owners
    metadata._http_factory = lambda: httpx.AsyncClient(transport=httpx.MockTransport(provider))
    metadata._receipts.clear()

    @server.app.get("/__qa__/stream-metadata")
    async def marker():
        return {"isolated_stream_metadata": True, "original_service": True, "synthetic_provider": True,
                "recovery_store_isolated": metadata._receipt_store.path.is_relative_to(root.resolve()),
                "real_credentials": False, "provider_traffic": False, "mode": state["mode"],
                "settling": state["settling"], "calls": deepcopy(state["calls"]),
                "owners": deepcopy(state["owners"]), "fields": deepcopy(state["fields"])}

    @server.app.post("/__qa__/stream-metadata/mode")
    async def mode(request: Request):
        raw = await request.body()
        if len(raw) > 64:
            return JSONResponse({"ok": False}, status_code=400)
        try:
            value = json.loads(raw)
        except (ValueError, TypeError):
            return JSONResponse({"ok": False}, status_code=400)
        if (not isinstance(value, dict) or set(value) != {"mode"}
                or not isinstance(value["mode"], str) or value["mode"] not in {"normal", "uncertain"}):
            return JSONResponse({"ok": False}, status_code=400)
        state.update(mode=value["mode"], settling=False)
        return {"ok": True, "synthetic_provider": True}


def setup(server, root):
    chat_setup(server, root)
    metadata_setup(server, root)
    service = server.twitch_account_service
    base = {"platform": "twitch", "state": "authorized", "reason": "account_authorized",
            "authorized": True, "streaming_authorized": False, "app_configured": True,
            "public_label": "fixture_channel", "account_ref": "a" * 64,
            "expires_at": time.time() + 3600}
    state = dict(base)
    calls = []

    def status():
        calls.append("status")
        return dict(state)

    async def begin():
        calls.append("begin")
        state.update(state="pending", reason="authorization_pending", flow_id="b" * 32,
                     user_code="DEMO-1234", verification_url="https://www.twitch.tv/activate",
                     expires_at=time.time() + 600, poll_after=5, authorization_kind="streaming")
        return dict(state)

    async def cancel():
        calls.append("cancel")
        state.clear()
        state.update(base)
        state["reason"] = "authorization_cancelled"
        return dict(state)

    async def check():
        calls.append("check")
        return dict(state)

    async def disconnect():
        calls.append("disconnect")
        state.clear()
        state.update(platform="twitch", state="not_authorized", reason="authorization_required",
                     authorized=False, streaming_authorized=False, app_configured=True)
        return dict(state)

    service.status = status
    service.begin = service.begin_streaming = begin
    service.cancel, service.check, service.disconnect = cancel, check, disconnect

    @server.app.get("/__qa__/desktop-accounts")
    async def marker():
        return {"isolated_desktop_accounts": True, "real_credentials": False,
                "provider_traffic": False, "calls": list(calls)}

    @server.app.post("/__qa__/desktop-accounts/authorize")
    async def authorize():
        state.clear()
        state.update(base, streaming_authorized=True)
        return JSONResponse({"synthetic_authorization": True})


if __name__ == "__main__":
    main(extra_setup=setup, extra_api_paths=("/api/production/viewer-chat",
         "/api/production/accounts", "/__qa__/desktop-accounts", "/api/production/stream-metadata",
         "/__qa__/stream-metadata"))
