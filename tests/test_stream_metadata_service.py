"""Synthetic metadata transport only: no vaults or real provider mutations."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import stat
from types import SimpleNamespace

import httpx
import pytest

from rareiq.services.stream_metadata_service import StreamMetadataService
from rareiq.core import stream_metadata_receipts as receipt_module


class Owner:
    def __init__(self, platform):
        self.record = {"access_token": "synthetic-private-token", "client_id": "synthetic-app",
                       "channel_id": "UCsynthetic_owned_channel" if platform == "youtube" else "123",
                       "public_label": "Synthetic owner", "scopes": [StreamMetadataService.EDIT_SCOPES[platform]]}
        self.lock = asyncio.Lock()
        self.generation, self.accesses = 0, []

    async def with_stream_info_access(self, operation, require_edit=False):
        async with self.lock:
            self.accesses.append(require_edit)
            generation = self.generation
            def guard():
                if generation != self.generation:
                    raise ValueError("account_state_changed")
            return await operation(deepcopy(self.record), guard)


class Fixture:
    def __init__(self, platform="twitch", *, receipt_path=None):
        self.platform, self.owner = platform, Owner(platform)
        self.calls, self.writes, self.hook = [], [], None
        self.title, self.category_id, self.tags = "Original title", "42", ["Original"]
        self.description = "Original description"
        self.video_etag = '"synthetic-fresh-etag"'
        self.category_items = [{"id": "42", "name": "Science"}]
        self.snippet = {"channelId": self.owner.record["channel_id"], "title": self.title,
                        "categoryId": "42", "description": self.description, "tags": self.tags,
                        "defaultLanguage": "en", "defaultAudioLanguage": "en-US",
                        "publishedAt": "2026-11-19T01:00:00Z", "thumbnails": {"private": "discard"}}
        self.broadcasts = [{"id": "event_1", "snippet": {"channelId": self.owner.record["channel_id"],
                             "title": self.title}, "status": {"lifeCycleStatus": "ready"}}]
        self.receipt_path = receipt_path
        self.restart()

    def restart(self):
        self.service = StreamMetadataService({self.platform: self.owner}, receipt_path=self.receipt_path,
            http_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(self.http)))

    async def http(self, request):
        assert request.url.scheme == "https"
        assert "access_token" not in request.url.params
        assert request.headers["Authorization"] == "Bearer synthetic-private-token"
        assert request.extensions["timeout"] == {"connect": 3, "read": 8, "write": 8, "pool": 8}
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, request.url.path, dict(request.url.params), deepcopy(body)))
        if self.hook:
            result = await self.hook(request, body)
            if result is not None:
                return result
        path = request.url.path
        if request.method != "GET":
            assert request.method in {"PATCH", "PUT"}
            self.writes.append(deepcopy(body))
            if self.platform == "youtube":
                assert request.url.params["part"] == "snippet"
                assert set(body) == {"id", "snippet"}
                self.snippet.update(body["snippet"])
                return httpx.Response(200, json={"id": "event_1"})
            self.title = body.get("title", body.get("stream_title", self.title))
            self.category_id = str(body.get("game_id", body.get("category_id", self.category_id)))
            self.tags = body.get("tags", body.get("custom_tags", self.tags))
            return httpx.Response(204)
        if path.endswith("liveBroadcasts"):
            items = self.broadcasts
            if "id" in request.url.params:
                items = [item for item in items if item["id"] == request.url.params["id"]]
            else:
                assert request.url.params["mine"] == "true"
                assert "broadcastStatus" not in request.url.params
            return httpx.Response(200, json={"items": items})
        if path.endswith("/videos"):
            item = {"id": "event_1", "snippet": self.snippet}
            if self.video_etag is not None:
                item["etag"] = self.video_etag
            return httpx.Response(200, json={"items": [item]})
        if path.endswith("videoCategories"):
            return httpx.Response(200, json={"items": [{"id": item["id"], "snippet": {
                "title": item["name"], "assignable": True}} for item in self.category_items]})
        if path.endswith("/categories") or path.endswith("/games"):
            if self.platform == "kick":
                assert path == "/public/v2/categories"
            return httpx.Response(200, json={"data": self.category_items})
        if path.endswith("/channels"):
            if self.platform == "twitch":
                data = {"broadcaster_id": self.owner.record["channel_id"], "title": self.title,
                        "game_id": self.category_id, "game_name": "Science", "tags": self.tags,
                        "stream_key": "must-never-be-exposed", "private": "discard"}
            else:
                assert not request.url.params
                data = {"broadcaster_user_id": int(self.owner.record["channel_id"]),
                        "stream_title": self.title, "category": {"id": int(self.category_id), "name": "Science"},
                        "stream": {"custom_tags": self.tags, "key": "must-never-be-exposed", "url": "secret"}}
            return httpx.Response(200, json={"data": [data]})
        raise AssertionError("Unexpected provider endpoint")

    async def apply(self, values, request_id="request_1", **kwargs):
        return await self.service.apply(self.platform, values, request_id, self.owner.record["channel_id"], **kwargs)


@pytest.mark.parametrize("platform", ["twitch", "kick", "youtube"])
def test_inspect_projects_public_metadata_and_reports_permission(platform):
    async def run():
        f = Fixture(platform)
        result = await f.service.inspect(platform, "event_1" if platform == "youtube" else None)
        assert result["authorized"] and result["editable"]
        assert result["fields"]["title"] == "Original title"
        assert result["capabilities"]["description"] == (platform == "youtube")
        serialized = json.dumps(result)
        assert not any(secret in serialized for secret in ("private-token", "synthetic-app", "must-never", "discard", "stream_key"))
        f.owner.record["scopes"] = []
        result = await f.service.inspect(platform)
        assert result["authorized"] and not result["editable"]
        assert result["reason"] == "stream_info_scope_required"
    asyncio.run(run())


def test_kick_unassigned_offline_channel_inspects_with_readonly_account():
    async def run():
        f = Fixture("kick")
        f.owner.record["scopes"] = []
        async def hook(request, body):
            return httpx.Response(200, json={"data": [{"broadcaster_user_id": 123, "stream_title": "",
                "category": {"id": 0, "name": ""}, "stream": {"custom_tags": None}}]})
        f.hook = hook
        result = await f.service.inspect("kick")
        assert result["authorized"] is True and result["editable"] is False
        assert result["channel_id"] == "123" and result["reason"] == "stream_info_scope_required"
        assert result["fields"] == {"title": "", "category_id": "", "category_name": "", "tags": []}
        assert not f.writes and len(f.calls) == 1 and f.calls[0][0] == "GET"
    asyncio.run(run())


@pytest.mark.parametrize("category,stream", [
    ({"id": 0, "name": "Science"}, {"custom_tags": None}),
    ({"id": "0", "name": ""}, {"custom_tags": None}),
    ({"id": False, "name": ""}, {"custom_tags": None}),
    ({"id": 0.0, "name": ""}, {"custom_tags": None}),
    ({"id": 0, "name": None}, {"custom_tags": None}),
    ({"id": 0, "name": ""}, {"custom_tags": False}),
    ({"id": 0, "name": ""}, {"custom_tags": ""}),
    ([], {"custom_tags": None}),
    ({"id": 0, "name": ""}, []),
])
def test_kick_only_normalizes_exact_unassigned_category_and_null_tags(category, stream):
    async def run():
        f = Fixture("kick")
        async def hook(request, body):
            return httpx.Response(200, json={"data": [{"broadcaster_user_id": 123, "stream_title": "",
                                                      "category": category, "stream": stream}]})
        f.hook = hook
        result = await f.service.inspect("kick")
        assert not result["authorized"] and result["reason"] == "invalid_provider_response"
        assert result["fields"] == {} and not f.writes
    asyncio.run(run())


def test_youtube_requires_explicit_owned_active_or_upcoming_selection():
    async def run():
        f = Fixture("youtube")
        f.broadcasts += [{"id": "foreign", "snippet": {"channelId": "UCforeign", "title": "Private other"},
                          "status": {"lifeCycleStatus": "live"}},
                         {"id": "completed", "snippet": {"channelId": f.owner.record["channel_id"], "title": "Finished"},
                          "status": {"lifeCycleStatus": "complete"}}]
        result = await f.service.inspect("youtube")
        assert result["reason"] == "broadcast_selection_required" and result["fields"] == {}
        assert [item["id"] for item in result["broadcasts"]] == ["event_1"]
        with pytest.raises(ValueError, match="^broadcast_selection_required$"):
            await f.apply({"title": "New"})
        with pytest.raises(ValueError, match="^broadcast_not_owned$"):
            await f.apply({"title": "New"}, broadcast_id="foreign")
        with pytest.raises(ValueError, match="^broadcast_unavailable$"):
            await f.apply({"title": "New"}, broadcast_id="completed")
        assert not f.writes
    asyncio.run(run())


def test_youtube_update_preserves_existing_mutable_snippet_and_never_changes_status():
    async def run():
        f = Fixture("youtube")
        result = await f.apply({"title": "New title", "category_id": ""}, broadcast_id="event_1")
        assert result["state"] == "applied" and len(f.writes) == 1
        assert f.writes[0] == {"id": "event_1", "snippet": {
            "title": "New title", "description": "Original description", "tags": ["Original"],
            "categoryId": "42", "defaultLanguage": "en", "defaultAudioLanguage": "en-US"}}
        assert [call[0] for call in f.calls] == ["GET", "GET", "PUT", "GET", "GET"]
        assert f.owner.accesses == [True]
    asyncio.run(run())


def test_youtube_uses_fresh_provider_etag_to_reject_concurrent_snippet_changes():
    async def run():
        f = Fixture("youtube")
        async def hook(request, body):
            if request.url.path.endswith("/videos") and request.method == "GET":
                return httpx.Response(200, json={"items": [{"id": "event_1", "etag": '"fresh-etag"',
                                                           "snippet": f.snippet}]})
            if request.method == "PUT":
                assert request.headers["If-Match"] == '"fresh-etag"'
                return httpx.Response(412, json={"message": "private stale state"})
        f.hook = hook
        with pytest.raises(ValueError, match="^provider_rejected$"):
            await f.apply({"title": "New"}, broadcast_id="event_1")
        assert not f.writes and not f.service._receipts
    asyncio.run(run())


@pytest.mark.parametrize("etag", [None, "*", '"one","two"', "é"])
def test_youtube_missing_or_unsafe_etag_prevents_full_snippet_put(etag):
    async def run():
        f = Fixture("youtube")
        f.video_etag = etag
        inspection = await f.service.inspect("youtube", "event_1")
        assert inspection["authorized"] and inspection["fields"]["title"] == "Original title"
        with pytest.raises(ValueError, match="^metadata_precondition_required$"):
            await f.apply({"title": "New title"}, broadcast_id="event_1")
        assert not f.writes and not f.service._receipts
        assert not any(call[0] == "PUT" for call in f.calls)
    asyncio.run(run())


@pytest.mark.parametrize("platform", ["twitch", "kick"])
def test_patch_updates_supported_fields_with_category_lookup_and_readback(platform):
    async def run():
        f = Fixture(platform)
        result = await f.apply({"title": "New title", "category_id": "42", "tags": ["Science"]})
        assert result["state"] == "applied"
        expected = {"title": "New title", "game_id": "42", "tags": ["Science"]} if platform == "twitch" else {
            "stream_title": "New title", "category_id": 42, "custom_tags": ["Science"]}
        assert f.writes == [expected]
        assert [call[0] for call in f.calls] == ["GET", "GET", "PATCH", "GET"]
        assert f.calls[1][2]["id"] == "42"
        result["fields"]["title"] = "tampered"
        again = await f.apply({"title": "New title", "category_id": "42", "tags": ["Science"]})
        assert again["fields"]["title"] == "New title" and len(f.writes) == 1
    asyncio.run(run())


def test_unknown_category_and_uneditable_grant_fail_before_write():
    async def run():
        f = Fixture()
        f.category_items = []
        with pytest.raises(ValueError, match="^category_not_found$"):
            await f.apply({"category_id": "999"})
        f.owner.record["scopes"] = []
        with pytest.raises(ValueError, match="^stream_info_scope_required$"):
            await f.apply({"title": "New"})
        assert not f.writes
    asyncio.run(run())


@pytest.mark.parametrize("values,code", [
    ({"description": "unsupported"}, "unsupported_metadata_field"),
    ({"privacyStatus": "public"}, "unsupported_metadata_field"),
    ({"title": " "}, "invalid_title"), ({"title": "a" * 101}, "invalid_title"),
    ({"title": "bad\nTitle"}, "invalid_title"), ({"category_id": "Science"}, "invalid_category_id"),
    ({"category_id": "0"}, "invalid_category_id"), ({"category_id": ""}, "no_metadata_changes"),
    ({"tags": ["has spaces"]}, "invalid_tags"), ({"tags": ["dup", "DUP"]}, "invalid_tags"),
    ({"tags": [str(n) for n in range(11)]}, "invalid_tags"),
])
def test_invalid_or_unsupported_metadata_never_contacts_provider(values, code):
    async def run():
        f = Fixture()
        with pytest.raises(ValueError, match="^" + code + "$"):
            await f.apply(values)
        assert not f.calls and not f.owner.accesses
    asyncio.run(run())


def test_youtube_tags_account_for_commas_and_quoted_spaces_and_description_bytes():
    async def run():
        f = Fixture("youtube")
        with pytest.raises(ValueError, match="^invalid_tags$"):
            await f.apply({"tags": ["a b" * 30 for _ in range(6)]}, broadcast_id="event_1")
        with pytest.raises(ValueError, match="^invalid_description$"):
            await f.apply({"description": "🙂" * 1251}, broadcast_id="event_1")
        assert not f.calls
    asyncio.run(run())


def test_request_id_conflict_and_account_change_cannot_reuse_receipt():
    async def run():
        f = Fixture()
        await f.apply({"title": "New"})
        with pytest.raises(ValueError, match="^request_id_conflict$"):
            await f.apply({"title": "Different"})
        f.owner.record["channel_id"] = "456"
        with pytest.raises(ValueError, match="^account_identity_mismatch$"):
            await f.service.apply("twitch", {"title": "New"}, "request_1", "123")
        assert len(f.writes) == 1
    asyncio.run(run())


def test_uncertain_write_reconciles_after_timeout_and_never_blindly_repeats():
    async def run():
        f = Fixture()
        failing = True
        async def hook(request, body):
            if request.method == "PATCH":
                f.writes.append(body)
                f.title = body["title"]
                raise httpx.ReadTimeout("provider echoed synthetic-private-token")
            if f.writes and failing:
                raise httpx.ConnectError("private transport state")
        f.hook = hook
        result = await f.apply({"title": "New"})
        assert result["state"] == "unconfirmed" and result["reason"] == "readback_unavailable"
        assert "private" not in json.dumps(result)
        again = await f.apply({"title": "New"})
        assert again["state"] == "unconfirmed" and len(f.writes) == 1
        failing = False
        result = await f.apply({"title": "New"})
        assert result["state"] == "applied" and len(f.writes) == 1
        assert [call[0] for call in f.calls] == ["GET", "PATCH", "GET", "GET", "GET"]
    asyncio.run(run())


def test_readback_mismatch_is_unconfirmed_and_exact_retry_does_not_rewrite():
    async def run():
        f = Fixture()
        async def hook(request, body):
            if request.method == "PATCH":
                f.writes.append(body)
                return httpx.Response(204)
        f.hook = hook
        result = await f.apply({"title": "New"})
        assert result["state"] == "unconfirmed" and result["reason"] == "readback_mismatch"
        again = await f.apply({"title": "New"})
        assert again["state"] == "unconfirmed" and len(f.writes) == 1
    asyncio.run(run())


def test_cancellation_after_transmission_retains_reconciliation_receipt():
    async def run():
        f = Fixture()
        async def hook(request, body):
            if request.method == "PATCH":
                f.writes.append(body)
                f.title = body["title"]
                raise asyncio.CancelledError()
        f.hook = hook
        with pytest.raises(asyncio.CancelledError):
            await f.apply({"title": "New"})
        result = await f.apply({"title": "New"})
        assert result["state"] == "applied" and len(f.writes) == 1
    asyncio.run(run())


def test_account_invalidation_during_preflight_blocks_write_and_suppresses_response():
    async def run():
        f = Fixture()
        async def hook(request, body):
            f.owner.generation += 1
        f.hook = hook
        with pytest.raises(ValueError, match="^account_state_changed$"):
            await f.apply({"title": "New"})
        assert not f.writes
        result = await f.service.inspect("twitch")
        assert not result["authorized"] and result["fields"] == {}
    asyncio.run(run())


def test_non_valueerror_owner_guard_reason_is_preserved_without_private_error_text():
    async def run():
        f = Fixture()
        class AccountError(Exception):
            pass
        original = f.owner.with_stream_info_access
        async def access(operation, require_edit=False):
            async def wrapped(record, guard):
                def owner_guard():
                    try:
                        guard()
                    except ValueError:
                        raise AccountError("account_state_changed") from None
                return await operation(record, owner_guard)
            return await original(wrapped, require_edit=require_edit)
        f.owner.with_stream_info_access = access
        async def hook(request, body):
            f.owner.generation += 1
        f.hook = hook
        with pytest.raises(ValueError, match="^account_state_changed$"):
            await f.apply({"title": "New"})
        assert not f.writes
    asyncio.run(run())


@pytest.mark.parametrize("status,reason", [(400, "provider_rejected"), (401, "authorization_rejected"),
    (403, "authorization_rejected"), (429, "provider_rate_limited"), (500, "provider_unavailable"),
    (302, "provider_unavailable")])
def test_provider_errors_are_allowlisted_and_redirects_are_not_followed(status, reason):
    async def run():
        f = Fixture()
        async def hook(request, body):
            return httpx.Response(status, json={"message": "private provider payload synthetic-private-token"},
                                  headers={"Location": "https://untrusted.example/steal"})
        f.hook = hook
        result = await f.service.inspect("twitch")
        assert result["reason"] == reason and len(f.calls) == 1
        assert "private" not in json.dumps(result)
    asyncio.run(run())


def test_response_size_and_invalid_json_are_bounded():
    async def run():
        f = Fixture()
        for body, reason in [(b"x" * (f.service.MAX_BYTES + 1), "provider_response_too_large"),
                             (b"not json private text", "invalid_provider_response")]:
            async def hook(request, _):
                return httpx.Response(200, content=body)
            f.hook = hook
            result = await f.service.inspect("twitch")
            assert result["reason"] == reason
    asyncio.run(run())


@pytest.mark.parametrize("platform", ["twitch", "kick", "youtube"])
def test_category_search_returns_only_bounded_official_id_and_name(platform):
    async def run():
        f = Fixture(platform)
        result = await f.service.categories(platform, "Science")
        assert result == {"platform": platform, "categories": [{"id": "42", "name": "Science"}]}
        assert not f.writes
    asyncio.run(run())


def test_concurrent_duplicate_updates_serialize_and_only_write_once():
    async def run():
        f = Fixture()
        results = await asyncio.gather(*[f.apply({"title": "New"}) for _ in range(8)])
        assert all(result["state"] == "applied" for result in results)
        assert len(f.writes) == 1
    asyncio.run(run())


def test_receipts_are_bounded_and_uncertain_entries_are_not_evicted():
    async def run():
        f = Fixture()
        f.service.MAX_RECEIPTS = 2
        async def hook(request, body):
            if request.method == "PATCH":
                f.writes.append(body)
                return httpx.Response(204)
        f.hook = hook
        await f.apply({"title": "One"}, "one")
        await f.apply({"title": "Two"}, "two")
        with pytest.raises(ValueError, match="^receipt_capacity_reached$"):
            await f.apply({"title": "Three"}, "three")
        assert len(f.service._receipts) == 2 and len(f.writes) == 2
    asyncio.run(run())


def test_durable_uncertainty_survives_restart_and_retry_only_reconciles(tmp_path):
    async def run():
        receipt_path = tmp_path / "metadata-receipts.json"
        f = Fixture(receipt_path=receipt_path)
        async def hook(request, body):
            if request.method == "PATCH":
                stored = json.loads(receipt_path.read_text())
                assert stored["receipts"][0]["state"] == "reserved"
                f.writes.append(body)
                raise httpx.ReadTimeout("Synthetic uncertain transmission")
        f.hook = hook
        assert (await f.apply({"title": "New"}))["state"] == "unconfirmed"
        f.restart()
        before = len(f.calls)
        retry = await f.apply({"title": "New"})
        assert retry["state"] == "unconfirmed" and retry["reason"] == "readback_mismatch"
        assert len(f.writes) == 1 and all(call[0] == "GET" for call in f.calls[before:])
        f.title = "New"
        f.restart()
        before = len(f.calls)
        assert (await f.apply({"title": "New"}))["state"] == "applied"
        assert len(f.writes) == 1 and all(call[0] == "GET" for call in f.calls[before:])
        assert json.loads(receipt_path.read_text())["receipts"][0]["state"] == "applied"
    asyncio.run(run())


def test_restarted_applied_receipt_requires_current_readback_and_never_rewrites(tmp_path):
    async def run():
        f = Fixture(receipt_path=tmp_path / "metadata-receipts.json")
        assert (await f.apply({"title": "New"}))["state"] == "applied"
        f.restart()
        before = len(f.calls)
        assert (await f.apply({"title": "New"}))["state"] == "applied"
        assert len(f.calls) == before + 1 and f.calls[-1][0] == "GET" and len(f.writes) == 1
        f.title = "Changed elsewhere"
        f.restart()
        result = await f.apply({"title": "New"})
        assert result["state"] == "unconfirmed" and result["reason"] == "readback_mismatch"
        assert len(f.writes) == 1
        assert json.loads(f.receipt_path.read_text())["receipts"][0]["state"] == "reserved"
    asyncio.run(run())


def test_durable_reservation_failure_blocks_provider_write_and_cleans_owned_temporary_file(tmp_path, monkeypatch):
    async def run():
        f = Fixture(receipt_path=tmp_path / "metadata-receipts.json")
        def fail_replace(*args):
            raise OSError("Synthetic private disk error")
        monkeypatch.setattr(receipt_module.os, "replace", fail_replace)
        with pytest.raises(ValueError, match="^metadata_recovery_storage_unavailable$"):
            await f.apply({"title": "New"})
        assert not f.writes and all(call[0] == "GET" for call in f.calls)
        assert not f.receipt_path.exists() and list(tmp_path.iterdir()) == []
    asyncio.run(run())


@pytest.mark.parametrize("raw", [
    b"not json",
    b'{"version":1,"receipts":[],"unexpected":true}',
    b'{"version":1,"version":1,"receipts":[]}',
    b'{"version":true,"receipts":[]}',
    json.dumps({"version": 1, "receipts": [{"platform": "twitch", "request_id": "one",
        "fingerprint": "a" * 64, "state": "reserved", "title": "must never be stored"}]}).encode(),
    json.dumps({"version": 1, "receipts": [{"platform": "twitch", "request_id": "one",
        "fingerprint": "invalid", "state": "reserved"}]}).encode(),
    json.dumps({"version": 1, "receipts": [{"platform": "twitch", "request_id": "one",
        "fingerprint": "a" * 64, "state": "unknown"}]}).encode(),
    b"x" * (receipt_module.StreamMetadataReceiptStore.MAX_BYTES + 1),
], ids=["invalid_json", "unknown_top_field", "duplicate_field", "boolean_version", "unknown_receipt_field",
        "invalid_fingerprint", "unknown_state", "oversized"])
def test_invalid_durable_storage_blocks_apply_before_credentials_but_not_inspection(tmp_path, raw):
    async def run():
        receipt_path = tmp_path / "metadata-receipts.json"
        receipt_path.write_bytes(raw)
        f = Fixture(receipt_path=receipt_path)
        with pytest.raises(ValueError, match="^metadata_recovery_storage_invalid$"):
            await f.apply({"title": "New"})
        assert not f.owner.accesses and not f.calls
        assert (await f.service.inspect("twitch"))["authorized"]
        assert (await f.service.categories("twitch", "Science"))["categories"][0]["id"] == "42"
        assert receipt_path.read_bytes() == raw and not f.writes
    asyncio.run(run())


def test_unreadable_receipt_parent_blocks_apply_before_account_access(tmp_path):
    async def run():
        parent = tmp_path / "regular-file"
        parent.write_text("Synthetic existing file")
        f = Fixture(receipt_path=parent / "metadata-receipts.json")
        with pytest.raises(ValueError, match="^metadata_recovery_storage_unavailable$"):
            await f.apply({"title": "New"})
        assert not f.owner.accesses and not f.calls and not f.writes
        assert (await f.service.inspect("twitch"))["authorized"]
    asyncio.run(run())


@pytest.mark.parametrize("kind", ["relative", "inside_source", "directory"])
def test_receipt_paths_must_be_absolute_outside_source_regular_files(tmp_path, kind):
    async def run():
        path = {"relative": Path("relative-receipt.json"),
                "inside_source": Path(__file__).resolve().parents[1] / "never-create-metadata-receipt.json",
                "directory": tmp_path}[kind]
        f = Fixture(receipt_path=path)
        with pytest.raises(ValueError, match="^metadata_recovery_storage_invalid$"):
            await f.apply({"title": "New"})
        assert not f.owner.accesses and not f.calls
        assert (await f.service.inspect("twitch"))["authorized"]
    asyncio.run(run())


def test_receipt_store_rejects_final_symlink_without_touching_target(tmp_path, monkeypatch):
    async def run():
        target, link = tmp_path / "target.json", tmp_path / "symlink.json"
        target.write_text('{"version":1,"receipts":[]}')
        try:
            link.symlink_to(target)
        except OSError:
            # Windows test accounts may lack symlink creation privileges. Still
            # exercise the lstat rejection, without requesting new privileges.
            original_lstat = Path.lstat
            def lstat(path, *args, **kwargs):
                return SimpleNamespace(st_mode=stat.S_IFLNK) if path == link else original_lstat(path, *args, **kwargs)
            monkeypatch.setattr(Path, "lstat", lstat)
        f = Fixture(receipt_path=link)
        with pytest.raises(ValueError, match="^metadata_recovery_storage_invalid$"):
            await f.apply({"title": "New"})
        assert not f.owner.accesses and not f.calls
        assert target.read_text() == '{"version":1,"receipts":[]}'
    asyncio.run(run())


def test_durable_file_contains_only_fingerprints_and_evicts_only_applied_receipts(tmp_path):
    async def run():
        f = Fixture(receipt_path=tmp_path / "metadata-receipts.json")
        f.service.MAX_RECEIPTS = 2
        for value in ("One", "Two", "Three"):
            assert (await f.apply({"title": value}, value.lower()))["state"] == "applied"
        stored = json.loads(f.receipt_path.read_text())
        assert set(stored) == {"version", "receipts"}
        assert [item["request_id"] for item in stored["receipts"]] == ["two", "three"]
        for item in stored["receipts"]:
            assert set(item) == {"platform", "request_id", "fingerprint", "state"}
            assert len(item["fingerprint"]) == 64 and item["state"] == "applied"
        assert not any(private in f.receipt_path.read_text() for private in
                       ("synthetic-private-token", "New title", "channel_id", "title", "description", "tags", "result"))
        async def hook(request, body):
            if request.method == "PATCH":
                f.writes.append(body)
                return httpx.Response(204)
        f.hook = hook
        assert (await f.apply({"title": "Uncertain one"}, "uncertain_one"))["state"] == "unconfirmed"
        assert (await f.apply({"title": "Uncertain two"}, "uncertain_two"))["state"] == "unconfirmed"
        before = len(f.writes)
        with pytest.raises(ValueError, match="^receipt_capacity_reached$"):
            await f.apply({"title": "Uncertain three"}, "uncertain_three")
        stored = json.loads(f.receipt_path.read_text())
        assert len(f.writes) == before and len(stored["receipts"]) == 2
        assert all(item["state"] == "reserved" for item in stored["receipts"])
        assert f.receipt_path.stat().st_size <= f.service._receipt_store.MAX_BYTES
    asyncio.run(run())


def test_post_readback_receipt_failure_preserves_applied_truth_and_restart_reconciles(tmp_path, monkeypatch):
    async def run():
        f = Fixture(receipt_path=tmp_path / "metadata-receipts.json")
        original_replace, attempts = receipt_module.os.replace, []
        def replace(source, destination):
            attempts.append(destination)
            if len(attempts) == 2:
                raise OSError("Synthetic private completion failure")
            return original_replace(source, destination)
        monkeypatch.setattr(receipt_module.os, "replace", replace)
        result = await f.apply({"title": "New"})
        assert result["state"] == "applied" and result["fields"]["title"] == "New"
        assert result["recovery_storage_warning"] is True
        assert json.loads(f.receipt_path.read_text())["receipts"][0]["state"] == "reserved"
        assert len(f.writes) == 1 and not list(tmp_path.glob("*.tmp"))
        f.restart()
        before = len(f.calls)
        result = await f.apply({"title": "New"})
        assert result["state"] == "applied" and not result.get("recovery_storage_warning")
        assert len(f.writes) == 1 and all(call[0] == "GET" for call in f.calls[before:])
        assert json.loads(f.receipt_path.read_text())["receipts"][0]["state"] == "applied"
    asyncio.run(run())


def test_cooperating_platform_services_merge_shared_durable_file(tmp_path):
    async def run():
        receipt_path = tmp_path / "metadata-receipts.json"
        twitch, kick = Fixture(receipt_path=receipt_path), Fixture("kick", receipt_path=receipt_path)
        results = await asyncio.gather(twitch.apply({"title": "Twitch new"}, "twitch_one"),
                                       kick.apply({"title": "Kick new"}, "kick_one"))
        assert all(result["state"] == "applied" for result in results)
        stored = json.loads(receipt_path.read_text())
        assert {(item["platform"], item["request_id"]) for item in stored["receipts"]} == {
            ("twitch", "twitch_one"), ("kick", "kick_one")}
        assert all(item["state"] == "applied" for item in stored["receipts"])
    asyncio.run(run())


def test_concurrent_platforms_in_one_service_keep_both_durable_and_cached_results(tmp_path):
    async def run():
        receipt_path = tmp_path / "metadata-receipts.json"
        twitch, kick = Fixture(), Fixture("kick")
        async def provider(request):
            return await (twitch.http(request) if request.url.host == "api.twitch.tv" else kick.http(request))
        service = StreamMetadataService({"twitch": twitch.owner, "kick": kick.owner}, receipt_path=receipt_path,
            http_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(provider)))
        twitch.service = kick.service = service
        values = await asyncio.gather(twitch.apply({"title": "Twitch new"}), kick.apply({"title": "Kick new"}))
        assert all(value["state"] == "applied" for value in values)
        before = (len(twitch.calls), len(kick.calls))
        assert (await twitch.apply({"title": "Twitch new"}))["state"] == "applied"
        assert (await kick.apply({"title": "Kick new"}))["state"] == "applied"
        assert (len(twitch.calls), len(kick.calls)) == before
        records = json.loads(receipt_path.read_text())["receipts"]
        assert len(records) == 2 and all(record["state"] == "applied" for record in records)
    asyncio.run(run())


def test_restarted_receipt_fingerprint_rejects_changed_request_without_provider_reads(tmp_path):
    async def run():
        f = Fixture(receipt_path=tmp_path / "metadata-receipts.json")
        await f.apply({"title": "New"})
        f.restart()
        before = len(f.calls)
        with pytest.raises(ValueError, match="^request_id_conflict$"):
            await f.apply({"title": "Changed request body"})
        assert len(f.calls) == before and len(f.writes) == 1
    asyncio.run(run())


@pytest.mark.parametrize("count,duplicate", [(129, False), (2, True)])
def test_overfull_or_duplicate_disk_receipts_block_before_credentials(tmp_path, count, duplicate):
    async def run():
        receipt_path = tmp_path / "metadata-receipts.json"
        receipt_path.write_text(json.dumps({"version": 1, "receipts": [
            {"platform": "twitch", "request_id": "same" if duplicate else str(index),
             "fingerprint": "a" * 64, "state": "reserved"} for index in range(count)]}))
        f = Fixture(receipt_path=receipt_path)
        with pytest.raises(ValueError, match="^metadata_recovery_storage_invalid$"):
            await f.apply({"title": "New"})
        assert not f.owner.accesses and not f.calls
    asyncio.run(run())


def test_durable_store_applies_owner_only_protection_before_atomic_replace(tmp_path, monkeypatch):
    async def run():
        original_owner_only, protected = receipt_module._owner_only, []
        def owner_only(path):
            protected.append(path)
            return original_owner_only(path)
        monkeypatch.setattr(receipt_module, "_owner_only", owner_only)
        f = Fixture(receipt_path=tmp_path / "metadata-receipts.json")
        assert (await f.apply({"title": "New"}))["state"] == "applied"
        assert len(protected) == 2 and all(path.parent == tmp_path and path.name.endswith(".tmp") for path in protected)
        assert f.receipt_path.is_file() and all(not path.exists() for path in protected)
    asyncio.run(run())
