"""Isolated public Kick metadata; no real grant, vault reads or provider calls."""
import time
from qa_native_desktop_fixture import main


def setup(server, root):
    public = {"platform": "kick", "state": "authorized", "reason": "account_authorized",
        "authorized": True, "streaming_authorized": True, "app_configured": True,
        "metadata_authorized": False, "account_ref": "a" * 64,
        "public_label": "fixture_kick", "expires_at": time.time() + 3600}
    server.kick_account_service.status = lambda: dict(public)
    async def check():
        return dict(public)
    server.kick_account_service.check = check


if __name__ == "__main__":
    main(rehearsal=True, extra_setup=setup,
        extra_api_paths=("/api/production/accounts",))
