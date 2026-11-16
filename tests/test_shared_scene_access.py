from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
import json

import pytest

from rareiq.web.shared_scene_access import (
    SharedSceneAccessMiddleware, SharedScenePolicy, VerifiedPrincipal,
)


PRINCIPAL = VerifiedPrincipal("stackthis", "producer-please", "member-one")
AUTHORIZATION = [(b"authorization", b"Bearer session-token")]


def _request(policy, *, method="GET", path="/api/production/scenes", headers=None,
             kind="http", extra=None):
    messages, handled = [], []
    scope = {"type": kind, "method": method, "path": path,
             "headers": AUTHORIZATION if headers is None else headers,
             "client": ("127.0.0.1", 45000), **(extra or {})}

    async def app(current_scope, receive, send):
        handled.append(current_scope.copy())

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        messages.append(message)

    current = policy if callable(policy) else lambda: policy
    asyncio.run(SharedSceneAccessMiddleware(app, current)(scope, receive, send))
    return messages, handled


def _status(messages):
    return next(message["status"] for message in messages if message["type"] == "http.response.start")


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/production/scenes"),
    ("GET", "/api/production/scenes/activity"),
    ("POST", "/api/production/scenes"),
    ("DELETE", "/api/production/scenes/scene-one"),
])
def test_allowed_scene_routes_receive_only_verified_principal(method, path):
    calls = []

    async def verify(token):
        calls.append(token)
        return PRINCIPAL

    messages, handled = _request(SharedScenePolicy(True, verify), method=method, path=path,
                                extra={"studio_principal": "forged"})
    assert not messages and len(handled) == 1
    assert calls == ["session-token"]
    assert handled[0]["studio_principal"] is PRINCIPAL


@pytest.mark.parametrize("method,path", [
    ("GET", "/control"), ("GET", "/api/boot/ping"), ("POST", "/remote-access"),
    ("GET", "/api/production/scenes/"), ("GET", "/api/production/scenes/scene-one"),
    ("POST", "/api/production/scenes/scene-one/take"),
    ("POST", "/api/production/switcher/take"), ("GET", "/api/cameras"),
    ("GET", "/api/output/camera/1/stream"), ("HEAD", "/api/production/scenes"),
    ("OPTIONS", "/api/production/scenes"), ("PUT", "/api/production/scenes"),
    ("DELETE", "/api/production/scenes/activity"), ("DELETE", "/api/production/scenes/"),
    ("DELETE", "/api/production/scenes/scene-one/take"),
    ("DELETE", "/api/production/scenes/.."), ("DELETE", "/api/production/scenes/a\\b"),
])
def test_unapproved_routes_deny_before_verifier_or_handler(method, path):
    calls = []

    async def verify(token):
        calls.append(token)
        return PRINCIPAL

    messages, handled = _request(SharedScenePolicy(True, verify), method=method, path=path)
    assert _status(messages) == 403
    assert not handled and not calls


@pytest.mark.parametrize("path", ["/ws", "/ws/output/camera/1", "/future-socket"])
def test_all_websockets_close_before_verifier_or_handler(path):
    async def verify(token):
        pytest.fail("WebSocket must not reach verifier")

    messages, handled = _request(SharedScenePolicy(True, verify), kind="websocket", path=path)
    assert messages == [{"type": "websocket.close", "code": 1008}]
    assert not handled


@pytest.mark.parametrize("headers", [
    [], [(b"cookie", b"rareiq_remote_session=paired")],
    [(b"x-forwarded-for", b"127.0.0.1"), (b"x-studio-role", b"owner")],
    [(b"authorization", b"")], [(b"authorization", b"Basic session-token")],
    [(b"authorization", b"Bearer")], [(b"authorization", b"Bearer ")],
    [(b"authorization", b"Bearer  session-token")],
    [(b"authorization", b"Bearer session-token,other")],
    [(b"authorization", b"Bearer session-token\n")],
    [(b"authorization", b"Bearer \xff")],
    [(b"authorization", b"Bearer " + b"x" * 8192)],
    AUTHORIZATION + AUTHORIZATION,
    AUTHORIZATION + [(b"Authorization", b"Bearer other")],
])
def test_only_one_well_formed_bearer_header_can_reach_verifier(headers):
    async def verify(token):
        pytest.fail("Malformed or absent authorization must not reach verifier")

    messages, handled = _request(SharedScenePolicy(True, verify), headers=headers,
                                extra={"query_string": b"token=session-token"})
    assert _status(messages) == 401 and not handled


@pytest.mark.parametrize("result", [None, {}, {"subject": "member-one", "role": "owner"}, "member-one"])
def test_invalid_verifier_results_fail_closed(result):
    async def verify(token):
        return result

    messages, handled = _request(SharedScenePolicy(True, verify))
    assert _status(messages) == 401 and not handled


def test_unavailable_or_failing_provider_never_exposes_credentials():
    async def verify(token):
        raise RuntimeError("secret-provider-error:" + token)

    for policy in (SharedScenePolicy(True), SharedScenePolicy(True, verify)):
        messages, handled = _request(policy)
        assert _status(messages) == 503 and not handled
        body = next(message["body"] for message in messages if message["type"] == "http.response.body")
        assert json.loads(body) == {"ok": False, "reason": "shared_scene_access_unavailable"}
        assert b"session-token" not in body and b"secret-provider-error" not in body
        assert (b"cache-control", b"no-store") in messages[0]["headers"]


@pytest.mark.parametrize("kind", ["http", "websocket", "lifespan"])
def test_disabled_policy_preserves_existing_behavior(kind):
    messages, handled = _request(SharedScenePolicy(), kind=kind, path="/any-route", headers=[])
    assert not messages and len(handled) == 1
    assert "studio_principal" not in handled[0]


def test_policy_is_read_for_each_request_and_failure_is_closed():
    policies = iter([SharedScenePolicy(), SharedScenePolicy(True)])
    current = lambda: next(policies)
    assert len(_request(current, path="/control")[1]) == 1
    assert _status(_request(current, path="/control")[0]) == 403
    assert _status(_request(current)[0]) == 503


@pytest.mark.parametrize("field", ["provider", "app_id", "subject"])
@pytest.mark.parametrize("invalid", [None, "", " ", " leading", "trailing ", "a\nb", "x" * 257])
def test_principal_requires_bounded_nonempty_identity_fields(field, invalid):
    values = {"provider": "stackthis", "app_id": "producer-please", "subject": "member-one"}
    values[field] = invalid
    with pytest.raises(ValueError, match="invalid_verified_principal"):
        VerifiedPrincipal(**values)


def test_principal_is_immutable_and_repr_omits_subject():
    with pytest.raises(FrozenInstanceError):
        PRINCIPAL.subject = "another-member"
    assert "member-one" not in repr(PRINCIPAL)


@pytest.mark.parametrize("status", [200, 403, 503])
def test_enabled_responses_never_cache_and_preserve_other_headers(status):
    messages = []
    original_headers = [(b"Cache-Control", b"public, max-age=300"), (b"x-service", b"scenes"),
                        (b"set-cookie", b"first=one"), (b"set-cookie", b"second=two")]

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": status, "headers": original_headers})
        await send({"type": "http.response.body", "body": b"result"})

    async def verify(token):
        return PRINCIPAL

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        messages.append(message)

    scope = {"type": "http", "method": "GET", "path": "/api/production/scenes",
             "headers": AUTHORIZATION}
    middleware = SharedSceneAccessMiddleware(app, lambda: SharedScenePolicy(True, verify))
    asyncio.run(middleware(scope, receive, send))
    assert messages[0]["status"] == status
    assert messages[0]["headers"] == original_headers[1:] + [(b"cache-control", b"no-store")]
    assert original_headers[0] == (b"Cache-Control", b"public, max-age=300")
    assert messages[1]["body"] == b"result"
