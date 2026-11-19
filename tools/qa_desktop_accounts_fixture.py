"""Isolated desktop-account HTTP fixture; no provider or real credential access."""
import time

from fastapi.responses import JSONResponse

from qa_greenroom_fixture import main
from qa_viewer_chat_fixture import setup as chat_setup


def setup(server, root):
    chat_setup(server, root)
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
         "/api/production/accounts", "/__qa__/desktop-accounts"))
