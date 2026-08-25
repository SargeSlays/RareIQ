# Meta broadcast connectors

RareIQ treats Facebook and Instagram as separate capabilities and never infers
platform state from OBS alone.

## Facebook Page route verification

The Facebook adapter is read-only. It authenticates a configured Page access
token against the expected Page ID, then privately compares the configured
Facebook RTMPS server and stream key with OBS. It never creates a LiveVideo,
changes Page content, or returns credentials through a RareIQ API.

Set these values only in the local RareIQ server environment:

```powershell
$env:RAREIQ_FACEBOOK_PAGE_ID = "your numeric Page ID"
$env:RAREIQ_FACEBOOK_PAGE_ACCESS_TOKEN = "your Page access token"
$env:RAREIQ_FACEBOOK_INGEST_URL = "rtmps://live-api-s.facebook.com:443/rtmp"
$env:RAREIQ_FACEBOOK_STREAM_KEY = "your Facebook stream key"
```

Restart RareIQ, open **Broadcast → Destinations**, and use **Check status**.
RareIQ sends the Page token only to Meta Graph over HTTPS. Tokens, stream keys,
and ingest URLs are kept out of the public status payload and logs.

Meta's current Graph API v26.0 reference says the Page `live_videos` edge does
not support a read operation. Creating a LiveVideo does return ingest URLs, but
RareIQ will not perform that write as part of a status check. Consequently:

- authenticated Page identity plus an exact OBS route can report **Ready**;
- OBS sending to that route does not become **Live verified**;
- no Page, route, or live claim is made after failed or stale evidence.

This distinction is intentional. A future Meta-supported read-only live-status
API can add platform acknowledgment without weakening the current route proof.

## Instagram capability gate

Meta's current Instagram content-publishing API documents images, videos,
reels, stories, and carousels. It does not expose Instagram Live Producer
ingest credentials or read-only live status. RareIQ therefore keeps Instagram
as an explicit setup/capability item and does not register a connector or claim
that an Instagram destination is Ready or Live.

Operators can continue using Instagram Live Producer outside RareIQ when their
account is eligible. RareIQ will add a connector only when Meta publishes an
API that can truthfully verify the account, destination route, and live state.
