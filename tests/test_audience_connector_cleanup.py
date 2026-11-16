"""A failed provider client must not prevent the rest of studio shutdown."""
import asyncio

import pytest

from rareiq.services.twitch_audience_connector import TwitchAudienceConnector
from rareiq.services.youtube_audience_connector import YouTubeAudienceConnector
from rareiq.services.kick_audience_connector import KickAudienceConnector


@pytest.mark.parametrize("kind", [TwitchAudienceConnector, YouTubeAudienceConnector, KickAudienceConnector])
@pytest.mark.parametrize("failure", ["raises", "stalls"])
def test_client_shutdown_is_bounded_and_discards_authorization(kind, failure):
    async def run():
        class Client:
            async def aclose(self):
                if failure == "raises":
                    raise RuntimeError("fixture cleanup failure")
                await asyncio.Future()
        connector = kind(None, lambda: {})
        connector.CLOSE_TIMEOUT_SECONDS = .01
        connector._http = Client()
        connector._token = connector._access_token = "fixture-private-token"
        result = await asyncio.wait_for(connector.close(), .3)
        assert connector._http is None
        assert connector.cached_status()["cleanup_incomplete"]
        assert not connector.cached_status()["connected"]
        assert not connector.cached_status()["authorized"]
        if kind is YouTubeAudienceConnector:
            assert connector._access_token is None
        else:
            assert connector._token is None
    asyncio.run(run())
