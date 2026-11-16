"""Guest-only ASGI boundary for a separate loopback listener in the SAME process.

An HTTPS reverse proxy may forward to this listener only. Forwarded headers and
cookies are never identity evidence. This wrapper does not terminate TLS, expose
a port, configure a proxy or own the main application's lifecycle.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import re
from urllib.parse import urlsplit

from .greenroom import PUBLIC_GUEST_PATHS


HTTP_METHODS = {path: frozenset({"GET", "POST"} if path == "/guest/chat" else
                              {"POST"} if path in {"/guest/join", "/guest/leave"} else {"GET", "HEAD"})
                for path in PUBLIC_GUEST_PATHS}
MAX_BODY_BYTES = 8192
MAX_HEADER_BYTES = 16384
MAX_WS_BYTES = 65536
SAFE_HEADERS = frozenset({b"host", b"origin", b"accept", b"accept-encoding", b"content-type",
                          b"sec-websocket-key", b"sec-websocket-version", b"sec-websocket-extensions"})


class GuestOnlyIngress:
    def __init__(self, app, *, public_origin):
        if not callable(app) or not isinstance(public_origin, str):
            raise ValueError("invalid_guest_ingress_configuration")
        if len(public_origin) > 300 or not re.fullmatch(r"https://[A-Za-z0-9.\-\[\]:]+/?", public_origin):
            raise ValueError("invalid_guest_ingress_origin")
        parsed = urlsplit(public_origin)
        try:
            port = parsed.port or 443
        except ValueError:
            raise ValueError("invalid_guest_ingress_origin") from None
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment or len(public_origin) > 300
                or not re.fullmatch(r"[A-Za-z0-9.\-\[\]:]+", parsed.netloc)
                or not 1 <= port <= 65535):
            raise ValueError("invalid_guest_ingress_origin")
        self.app = app
        self.authority = parsed.netloc.lower().encode("ascii")
        self.origin = "https://" + self.authority.decode("ascii")
        self.server = (parsed.hostname.lower(), port)

    async def _deny(self, scope, send, status=404):
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"), (b"cache-control", b"no-store"),
                                (b"x-content-type-options", b"nosniff")]})
        await send({"type": "http.response.body", "body": b'{"ok":false,"reason":"guest_ingress_rejected"}'})

    def _headers(self, scope):
        headers = scope.get("headers", [])
        if (len(headers) > 100 or any(not isinstance(k, bytes) or not isinstance(v, bytes) for k, v in headers)
                or sum(len(k) + len(v) for k, v in headers) > MAX_HEADER_BYTES):
            return None
        headers = [(key.lower(), value) for key, value in headers]
        if any(b"\r" in value or b"\n" in value or b"\x00" in value for _, value in headers):
            return None
        get = lambda name: [value for key, value in headers if key == name]
        if get(b"host") != [self.authority]:
            return None
        origins = get(b"origin")
        required = scope["type"] == "websocket" or scope.get("method") == "POST"
        if origins != [self.origin.encode()] and (required or origins):
            return None
        if len(get(b"content-length")) > 1 or len(get(b"content-type")) > 1 or len(get(b"authorization")) > 1:
            return None
        lengths = get(b"content-length")
        if lengths and (not re.fullmatch(rb"[0-9]{1,8}", lengths[0]) or int(lengths[0]) > MAX_BODY_BYTES):
            return None
        if lengths and get(b"transfer-encoding"):
            return None
        return headers

    async def __call__(self, scope, receive, send):
        kind = scope.get("type")
        if kind == "lifespan":
            # The operator server owns startup/shutdown of the shared app once.
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        if kind not in {"http", "websocket"}:
            raise ValueError("unsupported_guest_ingress_scope")
        path, raw = scope.get("path"), scope.get("raw_path")
        if (not isinstance(path, str) or not isinstance(raw, bytes) or scope.get("root_path", "")
                or not path.isascii() or raw != path.encode("ascii") or b"%" in raw or b"\\" in raw):
            return await self._deny(scope, send)
        if kind == "websocket":
            if path not in {"/guest/ws", "/guest/view/ws"} or scope.get("subprotocols"):
                return await self._deny(scope, send)
        elif path not in HTTP_METHODS or scope.get("method") not in HTTP_METHODS[path]:
            return await self._deny(scope, send)
        query = scope.get("query_string", b"")
        asset_query = (kind == "http" and path.startswith("/guest/assets/") and isinstance(query, bytes)
                       and re.fullmatch(rb"v=[A-Za-z0-9._-]{1,64}", query))
        chat_query = (kind == "http" and path == "/guest/chat" and scope.get("method") == "GET"
                      and isinstance(query, bytes) and re.fullmatch(
                          rb"(?:channel=(?:room|private)(?:&room_id=[a-f0-9]{32})?|room_id=[a-f0-9]{32}(?:&channel=(?:room|private))?)", query))
        if not isinstance(query, bytes) or query and not (asset_query or chat_query):
            return await self._deny(scope, send)
        headers = self._headers(scope)
        if headers is None:
            return await self._deny(scope, send, 403)
        clean_headers = [(k, v) for k, v in headers if k in SAFE_HEADERS]
        if path in {"/guest/leave", "/guest/chat"}:
            authorization = [v for k, v in headers if k == b"authorization"]
            if len(authorization) != 1 or not re.fullmatch(rb"Bearer [a-f0-9]{64}", authorization[0]):
                return await self._deny(scope, send, 401)
            clean_headers.append((b"authorization", authorization[0]))
        if path == "/guest/join" or path == "/guest/chat" and scope.get("method") == "POST":
            content_type = [v for k, v in headers if k == b"content-type"]
            if not content_type or content_type[0].split(b";", 1)[0].strip().lower() != b"application/json":
                return await self._deny(scope, send, 415)
        # Construct a fresh scope: no inherited cookies, principal, session,
        # proxy-rewritten path/client, middleware state, or operator identity.
        forwarded = {"type": kind, "asgi": {"version": "3.0", "spec_version": "2.4"},
                     "http_version": scope.get("http_version", "1.1"), "path": path, "raw_path": raw,
                     "root_path": "", "query_string": query, "headers": clean_headers,
                     "scheme": "wss" if kind == "websocket" else "https", "server": self.server,
                     "client": ("guest-ingress", 0)}
        if kind == "websocket":
            forwarded["subprotocols"] = []
            async def guest_receive():
                message = await receive()
                if message.get("type") == "websocket.receive":
                    text = message.get("text")
                    if message.get("bytes") is not None or not isinstance(text, str) or len(text.encode("utf-8")) > MAX_WS_BYTES:
                        await send({"type": "websocket.close", "code": 1009})
                        return {"type": "websocket.disconnect", "code": 1009}
                return message
            return await self.app(forwarded, guest_receive, send)
        forwarded["method"] = scope["method"]
        data = bytearray()
        limit = MAX_BODY_BYTES if path in {"/guest/join", "/guest/chat"} and scope["method"] == "POST" else 0
        try:
            async with asyncio.timeout(5):
                while True:
                    message = await receive()
                    if message.get("type") == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    if message.get("type") != "http.request" or not isinstance(chunk, bytes) or len(data) + len(chunk) > limit:
                        return await self._deny(scope, send, 413)
                    data.extend(chunk)
                    if not message.get("more_body", False):
                        break
        except asyncio.TimeoutError:
            return await self._deny(scope, send, 408)
        lengths = [v for k, v in headers if k == b"content-length"]
        if lengths and int(lengths[0]) != len(data):
            return await self._deny(scope, send, 400)
        clean_headers.append((b"content-length", str(len(data)).encode()))
        delivered = False
        async def guest_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(data), "more_body": False}
            message = await receive()
            return message if message.get("type") == "http.disconnect" else {"type": "http.disconnect"}
        async def guest_send(message):
            # HEAD uses the allowed GET handler without exposing a response body.
            if scope["method"] == "HEAD" and message.get("type") == "http.response.body":
                message = dict(message, body=b"")
            await send(message)
        if scope["method"] == "HEAD":
            forwarded["method"] = "GET"
        return await self.app(forwarded, guest_receive, guest_send)


def create_guest_listener(shared_app, *, public_origin, port, operator_port=8765):
    """Return an INACTIVE secondary server. Caller starts it after main startup.

    Both servers must receive the same app object in one process/event loop.
    Never configure an import string, workers, reload, external bind or proxy trust.
    """
    if (type(port) is not int or not 1024 <= port <= 65535
            or type(operator_port) is not int or not 1 <= operator_port <= 65535 or port == operator_port):
        raise ValueError("invalid_guest_ingress_port")
    import uvicorn
    class GuestListener(uvicorn.Server):
        @contextmanager
        def capture_signals(self):
            yield  # The primary operator server owns process signals.
    return GuestListener(uvicorn.Config(GuestOnlyIngress(shared_app, public_origin=public_origin),
        host="127.0.0.1", port=port, workers=1, reload=False, proxy_headers=False, forwarded_allow_ips=[],
        lifespan="off", access_log=False, server_header=False, ws_max_size=MAX_WS_BYTES,
        ws_max_queue=16, limit_concurrency=64, timeout_graceful_shutdown=5))
