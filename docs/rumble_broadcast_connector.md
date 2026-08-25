# Rumble broadcast connector

RareIQ's Rumble adapter reads the creator-owned Rumble Live Stream API. It can
verify the API resource, Rumble's current live flag, and—while a livestream is
active—the exact stream key and ingest URL configured in OBS. It does not
create streams, modify metadata, send chat, or collect credentials in Studio X.

## Local configuration

Create a Live Streaming API URL in the Rumble account dashboard. Rumble treats
that complete URL as a secret and allows it to be reset or revoked. Also copy
the RTMP or RTMPS ingest URL provided by Rumble for the destination configured
in OBS. Set both values only in the local RareIQ server environment:

```powershell
$env:RAREIQ_RUMBLE_LIVE_STREAM_API_URL = "your complete creator API URL"
$env:RAREIQ_RUMBLE_INGEST_URL = "your Rumble RTMP or RTMPS ingest URL"
```

Restart RareIQ, open **Broadcast → Destinations**, and use **Check status**.
RareIQ does not return either URL or any stream key from its APIs. Do not commit
them to Git.

## Verification model

Rumble's documented API is creator-specific and requires no separate
authorization header because its URL embeds the secret. RareIQ only accepts an
HTTPS API URL on `rumble.com`, disables redirects, limits the response size,
and validates the response's creator identity and livestream collection.

Rumble documents that livestream records are populated only while a stream is
live. Therefore, an offline connector can truthfully report **Connected**, but
it cannot report **Ready** before Rumble supplies an active stream key. During
an active stream, RareIQ compares that key and the locally configured Rumble
ingest URL with OBS entirely in memory. **Live verified** additionally requires
OBS itself to report streaming.

Static stream keys act as redirects and may not equal the active stream key in
the Live Stream API. RareIQ does not guess through that ambiguity. If Rumble
does not return the exact key currently stored in OBS, route verification stays
false.
