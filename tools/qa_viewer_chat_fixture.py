"""Loopback-only synthetic viewer/account fixture; no provider, device or real vault access."""
import re
import time

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse

from qa_greenroom_fixture import main
from rareiq.services.viewer_chat_service import TrustedViewerChatMessage


def setup(server, root):
    vault = server.platform_credential_vault
    if vault is not None:
        vault.get = lambda platform: {}
        vault.status = lambda platform: {"state": "empty", "stored": False}
        def blocked(*args, **kwargs):
            raise RuntimeError("Real credential writes are blocked in this fixture")
        vault.set = blocked
    accounts = {}
    for platform, service in (("twitch", server.twitch_account_service), ("youtube", server.youtube_account_service)):
        initial = {"platform": platform, "state": "not_authorized", "reason": "authorization_required",
                   "authorized": False, "app_configured": True}
        accounts[platform] = initial
        service.status = lambda platform=platform: dict(accounts[platform])
        async def begin(platform=platform):
            accounts[platform] = {**initial, "platform": platform, "state": "pending", "reason": "authorization_pending",
                                  "flow_id": ("a" if platform == "twitch" else "b") * 32,
                                  "expires_at": time.time() + 600}
            if platform == "twitch":
                accounts[platform].update(user_code="DEMO-1234", verification_url="https://www.twitch.tv/activate", poll_after=5)
            return dict(accounts[platform])
        async def cancel(platform=platform):
            accounts[platform] = {**initial, "platform": platform, "reason": "authorization_cancelled"}
            return dict(accounts[platform])
        service.begin, service.cancel = begin, cancel
    states = {}
    for platform, connector in (("twitch", server.twitch_audience_connector), ("youtube", server.youtube_audience_connector), ("kick", server.kick_audience_connector)):
        states[platform] = {"platform": platform, "implemented": True, "state": "not_connected", "reason": "explicit_connection_required",
                            "connected": False, "authorized": False, "verified": False, "dashboard_registration_approved": False}
        connector.cached_status = lambda platform=platform: dict(states[platform])
        async def connect(platform=platform):
            if platform != "kick":
                states[platform].update(state="connected", reason="observing_chat", connected=True, authorized=True, verified=True)
            return dict(states[platform])
        async def disconnect(platform=platform):
            states[platform].update(state="not_connected", reason="disconnected_by_operator", connected=False, authorized=False, verified=False)
            return dict(states[platform])
        connector.connect, connector.disconnect = connect, disconnect
    async def no_refresh():
        return None
    server.twitch_account_service.ensure_credentials = no_refresh
    count = 0

    @server.app.get("/__qa__/viewer-chat")
    async def page():
        control = (server.STATIC_DIR / "control.html").read_text(encoding="utf-8")
        styles = "\n".join(re.findall(r'<link rel="stylesheet"[^>]+>', control))
        return HTMLResponse('<!doctype html><html data-theme="dark" data-operator-skin="ignite"><head>' + styles + '</head><body class="pp-shell studiox-ui4 studiox-premium studiox-command-deck" data-operator-layout="v2" data-studiox-visual-system="unified">'
            '<main id="chatFixture" style="padding:24px;max-width:880px;margin:auto"></main>'
            '<script src="/static/platform_accounts.js?v=fixture"></script><script src="/static/viewer_chat.js?v=fixture"></script>'
            '<script>window.chatFixture=ProducerViewerChat.mount(document.getElementById("chatFixture"));</script></body></html>')

    @server.app.get("/__qa__/viewer-chat-marker")
    async def marker():
        return {"synthetic_viewer_chat_fixture": True, "provider_network": False, "hardware": False,
                "real_credentials": False, "program_generation": server.PRODUCTION_SWITCHER_STATE["generation"]}

    @server.app.post("/__qa__/viewer-chat-message")
    async def message(request: Request):
        nonlocal count
        raw = await request.body()
        if len(raw) > 128:
            return JSONResponse({"ok": False}, status_code=400)
        value = await request.json()
        if not isinstance(value, dict) or set(value) - {"platform", "count"} or value.get("platform") not in states:
            return JSONResponse({"ok": False}, status_code=400)
        number = value.get("count", 1)
        if type(number) is not int or not 1 <= number <= 330:
            return JSONResponse({"ok": False}, status_code=400)
        results = []
        for _ in range(number):
            count += 1
            results.append(server.viewer_chat_service.accept(TrustedViewerChatMessage(value["platform"], "fixture-channel",
                "fixture-" + str(count), "fixture-author", "Synthetic viewer", 'Synthetic message <img src=x onerror=alert(1)> #' + str(count), time.time())))
        return {"ok": all(r["ok"] for r in results), "generated": number}


if __name__ == "__main__":
    main(extra_setup=setup, extra_api_paths=("/api/production/viewer-chat", "/api/production/accounts", "/__qa__/viewer-chat-message"))
