# X Media Studio broadcast connector

RareIQ's X adapter verifies the private encoder route supplied by X Media
Studio Producer. It does not create a source or broadcast, post on X, access
analytics, or collect credentials in Studio X.

## Local configuration

In X Media Studio Producer, create or select an RTMP source and copy its RTMP
or RTMPS URL and stream key. Configure the same values in OBS, then set them in
the local RareIQ server environment:

```powershell
$env:RAREIQ_X_INGEST_URL = "your X Media Studio RTMP or RTMPS URL"
$env:RAREIQ_X_STREAM_KEY = "your X Media Studio source key"
```

Restart RareIQ, open **Broadcast → Destinations**, and use **Check status**.
RareIQ compares both values with OBS entirely in memory. Neither value appears
in RareIQ's public status payload, logs, or UI. Do not commit them to Git.

## Verification boundary

X documents that Media Studio Producer supplies a source URL and stream key for
external encoders. X does not document a general public, read-only Producer API
for source or live-broadcast status. RareIQ therefore uses these states:

- **Configured**: a valid local X source route exists, but OBS does not exactly
  match both values;
- **Ready**: OBS reports the exact configured source URL and stream key;
- never **Live verified** from encoder activity alone.

OBS streaming to the matching route proves encoder egress, not that X has
accepted or published a broadcast. A future supported X status API can add
platform acknowledgment without weakening this route boundary.

## TikTok status

TikTok's current developer product catalog exposes Login Kit, Display API,
Content Posting API, Research API, and related products, but no general LIVE
ingest or status API. RareIQ therefore keeps TikTok capability-gated and does
not fabricate a connector from profile, video, embed, or OBS state.
