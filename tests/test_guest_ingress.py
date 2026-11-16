"""Guest boundary tests use in-memory ASGI only; never bind a listener."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from rareiq.services.greenroom_service import GreenroomService
from rareiq.web.greenroom import GreenroomHub, PUBLIC_GUEST_PATHS
from rareiq.web.guest_ingress import GuestOnlyIngress, create_guest_listener, MAX_BODY_BYTES


ORIGIN = "https://guests.example.test"
AUTHORITY = b"guests.example.test"


def scope(path="/guest", *, kind="http", method="GET", **extra):
    value = {"type": kind, "path": path, "raw_path": path.encode(), "method": method,
             "root_path": "", "query_string": b"", "headers": [(b"host", AUTHORITY), (b"origin", ORIGIN.encode())],
             "scheme": "http", "server": ("127.0.0.1", 8766), "client": ("127.0.0.1", 54321)}
    if method == "POST":
        value["headers"].append((b"content-type", b"application/json"))
    value.update(extra)
    return value


def exercise(incoming, packets=None):
    calls, sent = [], []
    async def target(value, receive, send):
        calls.append((value, await receive()))
        if value["type"] == "http":
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"fixture"})
    wrapper = GuestOnlyIngress(target, public_origin=ORIGIN)
    messages = list(packets or [{"type": "http.request", "body": b"", "more_body": False}])
    async def receive():
        return messages.pop(0) if messages else {"type": "http.disconnect"}
    async def send(message):
        sent.append(message)
    asyncio.run(wrapper(incoming, receive, send))
    return calls, sent


@pytest.mark.parametrize("path", sorted(PUBLIC_GUEST_PATHS - {"/guest/join", "/guest/leave"}))
@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_only_exact_guest_documents_and_assets_are_readable(path, method):
    calls, sent = exercise(scope(path, method=method))
    assert len(calls) == 1 and calls[0][0]["method"] == "GET"
    assert sent[-1]["body"] == (b"" if method == "HEAD" else b"fixture")


@pytest.mark.parametrize("path", ["/", "/control", "/docs", "/openapi.json", "/static/guest.js", "/api/production/greenroom",
    "/api/production/switcher/take", "/guest/", "/guest/join/", "/guest/ws", "/guest/assets/unknown.js", "/guest/../control",
    "//guest", "/guest%2fjoin", "/guest\\join", "/%67uest"])
def test_unknown_admin_and_noncanonical_http_paths_never_reach_app(path):
    calls, sent = exercise(scope(path))
    assert not calls and sent[0]["status"] == 404


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE", "CONNECT", "TRACE", "OPTIONS", "POST"])
def test_unknown_methods_cannot_reach_guest_page(method):
    calls, _ = exercise(scope(method=method))
    assert not calls


@pytest.mark.parametrize("extra", [{"raw_path": b"/%67uest"}, {"raw_path": b"/guest%2f..%2fcontrol"},
    {"raw_path": b"//guest"}, {"raw_path": None}, {"root_path": "/admin"}, {"query_string": b"invite=secret"}])
def test_raw_path_root_and_token_query_must_be_canonical(extra):
    calls, _ = exercise(scope(**extra))
    assert not calls


@pytest.mark.parametrize("query", [b"v=x&redirect=/control", b"v=%2f", b"v=" + b"a" * 65, b"token=secret", b"v=1;v=2"])
def test_asset_query_only_allows_bounded_version(query):
    calls, _ = exercise(scope("/guest/assets/guest.js", query_string=query))
    assert not calls
    calls, _ = exercise(scope("/guest/assets/guest.js", query_string=b"v=20261115-1"))
    assert len(calls) == 1


@pytest.mark.parametrize("headers", [[], [(b"host", b"127.0.0.1:8766")], [(b"host", AUTHORITY), (b"host", AUTHORITY)],
    [(b"host", AUTHORITY), (b"origin", b"https://untrusted.test")],
    [(b"host", AUTHORITY), (b"origin", ORIGIN.encode()), (b"origin", ORIGIN.encode())]])
def test_host_and_origin_are_exact_not_forwarded(headers):
    calls, sent = exercise(scope(headers=headers))
    assert not calls and sent[0]["status"] == 403


def test_operator_identity_cookies_and_forwarding_headers_are_removed():
    incoming = scope(studio_principal=object(), user=object(), auth="operator", session={"admin": True}, state={"operator": True})
    incoming["headers"] += [(b"cookie", b"operator=private"), (b"authorization", b"Bearer operator-secret"),
        (b"forwarded", b"host=localhost;proto=http"), (b"x-forwarded-for", b"127.0.0.1"), (b"x-original-url", b"/control")]
    calls, _ = exercise(incoming)
    forwarded = calls[0][0]
    assert not set(forwarded) & {"studio_principal", "user", "auth", "session", "state"}
    assert forwarded["client"] == ("guest-ingress", 0) and forwarded["scheme"] == "https"
    assert dict(forwarded["headers"]).keys() == {b"host", b"origin", b"content-length"}


def test_bounded_join_body_and_only_leave_preserves_guest_bearer():
    incoming = scope("/guest/join", method="POST")
    calls, _ = exercise(incoming, [{"type": "http.request", "body": b"{", "more_body": True},
                                 {"type": "http.request", "body": b"}", "more_body": False}])
    assert calls[0][1]["body"] == b"{}"
    calls, sent = exercise(incoming, [{"type": "http.request", "body": b"x" * (MAX_BODY_BYTES + 1)}])
    assert not calls and sent[0]["status"] == 413
    calls, _ = exercise(scope(), [{"type": "http.request", "body": b"unexpected"}])
    assert not calls
    leave = scope("/guest/leave", method="POST")
    calls, sent = exercise(leave)
    assert not calls and sent[0]["status"] == 401
    leave["headers"].append((b"authorization", b"Bearer " + b"a" * 64))
    calls, _ = exercise(leave)
    assert dict(calls[0][0]["headers"])[b"authorization"] == b"Bearer " + b"a" * 64


@pytest.mark.parametrize("headers", [[(b"content-length", b"9000")], [(b"content-length", b"-1")],
    [(b"content-length", b"0"), (b"content-length", b"0")], [(b"content-length", b"0"), (b"transfer-encoding", b"chunked")],
    [(b"content-length", b"2")], [(b"x-extra", b"x" * 17000)]])
def test_body_and_header_framing_cannot_bypass_limits(headers):
    incoming = scope("/guest/join", method="POST")
    incoming["headers"] += headers
    calls, _ = exercise(incoming)
    assert not calls


@pytest.mark.parametrize("path", ["/api/production/greenroom/producer-socket", "/api/production/greenroom/output-socket", "/guest", "/guest/ws/", "/ws"])
def test_only_guest_websocket_path_can_upgrade(path):
    calls, sent = exercise(scope(path, kind="websocket"))
    assert not calls and sent == [{"type": "websocket.close", "code": 1008}]


def test_guest_socket_has_no_cookie_principal_or_subprotocol_escape():
    incoming = scope("/guest/ws", kind="websocket", subprotocols=["operator-secret"])
    calls, _ = exercise(incoming)
    assert not calls
    incoming["subprotocols"] = []
    calls, _ = exercise(incoming, [{"type": "websocket.connect"}])
    assert calls[0][0]["scheme"] == "wss" and calls[0][1]["type"] == "websocket.connect"
    calls, sent = exercise(incoming, [{"type": "websocket.receive", "bytes": b"binary"}])
    assert sent[0] == {"type": "websocket.close", "code": 1009}
    assert calls[0][1] == {"type": "websocket.disconnect", "code": 1009}
    calls, sent = exercise(incoming, [{"type": "websocket.receive", "text": "x" * 65537}])
    assert sent[0]["code"] == 1009
    incoming["headers"] = [(b"host", AUTHORITY)]
    calls, sent = exercise(incoming, [{"type": "websocket.connect"}])
    assert not calls and sent[0]["code"] == 1008


def test_wrapper_shares_same_hub_without_duplicating_lifespan(tmp_path):
    events = []
    @asynccontextmanager
    async def lifespan(app):
        events.append("start")
        yield
        events.append("stop")
    app = FastAPI(lifespan=lifespan)
    service = GreenroomService(tmp_path / "room.sqlite3")
    hub = GreenroomHub(service, authorize_operator=lambda _: False,
        switcher=lambda: {"program_slot": 1, "preview_slot": 2, "generation": 0},
        static_dir=Path(__file__).parents[1] / "rareiq/web/static", public_origin=lambda: ORIGIN)
    app.include_router(hub.router)
    invitation = service.create_invite()
    wrapper = GuestOnlyIngress(app, public_origin=ORIGIN)
    with TestClient(app), TestClient(wrapper, base_url=ORIGIN, headers={"origin": ORIGIN}) as guest:
        assert events == ["start"]
        response = guest.post("/guest/join", json={"invite_token": invitation["token"], "name": "Fixture guest", "session_token": "a" * 64})
        assert response.status_code == 200 and len(service.snapshot()["participants"]) == 1
        assert guest.get("/api/production/greenroom").status_code == 404
        with guest.websocket_connect("wss://guests.example.test/guest/ws") as connection:
            connection.send_json({"type": "authenticate", "token": "a" * 64})
            hello = connection.receive_json()
            assert hello["role"] == "guest" and hello["peer_id"] in hub.peers
    assert events == ["start", "stop"]


def test_listener_factory_is_inactive_loopback_and_owns_no_lifespan():
    async def app(scope, receive, send):
        pass
    listener = create_guest_listener(app, public_origin=ORIGIN, port=8766)
    assert not listener.started and listener.config.app.app is app
    assert listener.config.host == "127.0.0.1" and listener.config.port == 8766
    assert listener.config.lifespan == "off" and listener.config.proxy_headers is False
    assert listener.config.workers == 1 and not listener.config.access_log
    for port in (8765, 0, True, 65536):
        with pytest.raises(ValueError):
            create_guest_listener(app, public_origin=ORIGIN, port=port)


@pytest.mark.parametrize("origin", ["http://guests.example.test", "https://user:password@guests.example.test",
    "https://guests.example.test/prefix", "https://guests.example.test?token=secret", "https://guests.example.test:99999",
    "https://guests.example.test#fragment", "https://guests.example.test\r\n", ""])
def test_invalid_origin_cannot_create_boundary(origin):
    async def app(scope, receive, send):
        pass
    with pytest.raises(ValueError):
        GuestOnlyIngress(app, public_origin=origin)
