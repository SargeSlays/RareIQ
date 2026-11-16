from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json as jsonlib

import httpx
import pytest

from rareiq.services import stackthis_identity as identity
from rareiq.web.shared_scene_access import VerifiedPrincipal


TOKEN = "a" * 64  # Offline fixture, never a live credential.


def _payload(**changes):
    return {"allowed": True, "appId": "producer-please", "subject": "test-member",
            "source": "free", "checkedAt": datetime.now(timezone.utc).isoformat(), **changes}


def _verify(handler, token=TOKEN):
    verifier = identity.StackThisSessionVerifier(transport=httpx.MockTransport(handler))
    return asyncio.run(verifier(token))


def _response(status, *, json=None, content=b"", headers=None, stream=None):
    response_headers = dict(headers or {})
    if json is not None:
        content = jsonlib.dumps(json).encode()
        response_headers.setdefault("content-type", "application/json")
    if stream is None:
        response_headers.setdefault("content-length", str(len(content)))
        stream = _Chunks([content])
    return httpx.Response(status, headers=response_headers, stream=stream)


def test_exact_server_only_contract_and_repeated_verification_without_cookies(monkeypatch):
    requests = []
    monkeypatch.setenv("HTTPS_PROXY", "http://invalid.proxy.invalid:1")
    monkeypatch.setenv("SSL_CERT_FILE", "missing-test-certificate.pem")

    def handler(request):
        requests.append(request)
        assert request.method == "GET"
        assert str(request.url) == "https://stackthis.binary6labs.com/api/apps/session/check?appId=producer-please"
        assert request.headers["authorization"] == "Bearer " + TOKEN
        assert request.headers["accept"] == "application/json"
        assert request.headers["accept-encoding"] == "identity"
        assert request.headers["cache-control"] == "no-store"
        assert request.headers["pragma"] == "no-cache"
        assert not any(header in request.headers for header in ("origin", "sec-fetch-site", "cookie", "x-stackthis-device"))
        assert all(value <= 5 for value in request.extensions["timeout"].values())
        return _response(200, json=_payload(source="purchase"), headers={"Set-Cookie": "provider=ignored"})

    async def run():
        verifier = identity.StackThisSessionVerifier(transport=httpx.MockTransport(handler))
        for _ in range(2):
            assert await verifier(TOKEN) == VerifiedPrincipal("stackthis", "producer-please", "test-member")

    asyncio.run(run())
    assert len(requests) == 2


@pytest.mark.parametrize("token", [None, "", "a" * 63, "a" * 65, "A" * 64, "g" * 64, " " + TOKEN, TOKEN + "\n"])
def test_malformed_tokens_are_rejected_without_request(token):
    def handler(request):
        pytest.fail("Invalid bearer token reached transport")

    assert _verify(handler, token) is None


@pytest.mark.parametrize("status", [401, 403])
def test_expired_or_denied_sessions_return_none(status):
    assert _verify(lambda request: _response(status, content=b"not identity data")) is None


@pytest.mark.parametrize("status", [201, 204, 301, 302, 307, 308, 400, 404, 429, 500, 503])
def test_other_statuses_and_unregistered_app_fail_unavailable_without_redirect(status):
    requests = []

    def handler(request):
        requests.append(request)
        return _response(status, headers={"location": "https://untrusted.invalid/"}, json=_payload())

    with pytest.raises(identity.StackThisIdentityUnavailable, match="^stackthis_identity_unavailable$"):
        _verify(handler)
    assert len(requests) == 1


@pytest.mark.parametrize("changes", [
    {"allowed": False}, {"allowed": 1}, {"allowed": "true"}, {"appId": "other-app"},
    {"subject": ""}, {"subject": None}, {"subject": "x" * 257}, {"subject": " member"},
    {"subject": "member\nname"}, {"source": None}, {"source": ""}, {"role": "owner"},
    {"checkedAt": None}, {"checkedAt": "2026-11-15"}, {"checkedAt": "2026-11-15T01:00:00"},
    {"checkedAt": "2026-99-15T01:00:00Z"},
])
def test_invalid_identity_schema_never_grants_identity(changes):
    with pytest.raises(identity.StackThisIdentityUnavailable):
        _verify(lambda request: _response(200, json=_payload(**changes)))


@pytest.mark.parametrize("offset", [-61, 6])
def test_stale_or_future_verification_is_rejected(offset):
    checked = (datetime.now(timezone.utc) + timedelta(seconds=offset)).isoformat()
    with pytest.raises(identity.StackThisIdentityUnavailable):
        _verify(lambda request: _response(200, json=_payload(checkedAt=checked)))


def test_aware_utc_z_timestamp_is_accepted():
    checked = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    assert _verify(lambda request: _response(200, json=_payload(checkedAt=checked))).subject == "test-member"


@pytest.mark.parametrize("content", [b"not json", b"[]", b"{}", b"\xff", b'{"allowed":true,"allowed":true}'])
def test_malformed_incomplete_or_duplicate_json_is_rejected(content):
    with pytest.raises(identity.StackThisIdentityUnavailable):
        _verify(lambda request: _response(200, content=content, headers={"content-type": "application/json"}))


@pytest.mark.parametrize("headers", [
    {"content-type": "text/html"}, {"content-type": "application/json", "content-encoding": "gzip"},
    {"content-type": "application/json", "content-length": "16385"},
    {"content-type": "application/json", "content-length": "invalid"},
])
def test_invalid_media_encoding_or_declared_length_is_rejected(headers):
    with pytest.raises(identity.StackThisIdentityUnavailable):
        _verify(lambda request: _response(200, content=jsonlib.dumps(_payload()).encode(), headers=headers))


class _Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks, self.closed = chunks, False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self):
        self.closed = True


def test_streamed_oversize_body_is_bounded_without_content_length():
    stream = _Chunks([b" " * 8192, b" " * 8192, b"x"])
    with pytest.raises(identity.StackThisIdentityUnavailable):
        _verify(lambda request: _response(200, stream=stream, headers={"content-type": "application/json"}))
    assert stream.closed


def test_transport_failures_are_generic_without_secret_exception_context():
    def handler(request):
        raise httpx.ConnectError("private detail " + TOKEN, request=request)

    with pytest.raises(identity.StackThisIdentityUnavailable) as failure:
        _verify(handler)
    assert str(failure.value) == "stackthis_identity_unavailable"
    assert failure.value.__context__ is None
    assert failure.value.__cause__ is None


def test_total_deadline_covers_slow_response(monkeypatch):
    monkeypatch.setattr(identity, "TIMEOUT_SECONDS", 0.01)

    async def handler(request):
        await asyncio.sleep(1)
        return _response(200, json=_payload())

    with pytest.raises(identity.StackThisIdentityUnavailable):
        _verify(handler)
