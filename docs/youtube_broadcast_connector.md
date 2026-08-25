# YouTube Live broadcast connector

RareIQ's YouTube adapter is a read-only monitor for an explicitly configured
channel. It validates the authenticated channel, checks active broadcasts, and
can prove that OBS uses an ingestion stream owned by that channel. It does not
create, modify, transition, or delete YouTube broadcasts.

## Local configuration

Create a Google Cloud OAuth client and authorize the least-privilege scope:

`https://www.googleapis.com/auth/youtube.readonly`

Request offline access so the authorization flow returns a refresh token, then
set these values in the local RareIQ server environment:

```powershell
$env:RAREIQ_YOUTUBE_CLIENT_ID = "your OAuth client ID"
$env:RAREIQ_YOUTUBE_CLIENT_SECRET = "your OAuth client secret"
$env:RAREIQ_YOUTUBE_REFRESH_TOKEN = "your offline refresh token"
$env:RAREIQ_YOUTUBE_CHANNEL_ID = "your expected UC... channel ID"
```

Restart RareIQ, open **Broadcast → Destinations**, and use **Check status**.
RareIQ does not accept these credentials through Studio X or return them from
its APIs. Do not commit credentials to Git.

## Verification model

The connector requires the authenticated account's channel ID to match the
configured channel ID. If OBS is configured for YouTube, RareIQ privately
compares the OBS key with stream names returned by `liveStreams.list`. Reusable
streams and streams bound to active or upcoming broadcasts are supported.

Access tokens and ingestion stream names stay in memory. They are never
returned, logged, hashed for display, or persisted by this connector. The
destination becomes **Ready** only after exact key correlation. **Live
verified** additionally requires OBS to be streaming while YouTube reports an
active broadcast with a live lifecycle state.

Authentication errors, channel mismatches, missing streams, malformed API
responses, and route mismatches all fail closed.
