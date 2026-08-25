# Twitch broadcast connector

RareIQ's first Twitch adapter is a read-only channel monitor. It confirms that
the configured Twitch channel exists and reports whether Twitch currently lists
that channel as live. It does not configure OBS, read a stream key, start a
stream, or claim that the live Twitch stream is RareIQ's encoder output.

## Local configuration

Register a Twitch developer application, then set these values in the local
RareIQ server environment:

```powershell
$env:RAREIQ_TWITCH_CLIENT_ID = "your application client ID"
$env:RAREIQ_TWITCH_CLIENT_SECRET = "your application client secret"
$env:RAREIQ_TWITCH_CHANNEL_LOGIN = "your_channel_login"
```

Restart RareIQ after changing the environment. Open **Broadcast →
Destinations**, then use **Check status** on the Twitch destination.

The client secret and access token remain server-side and in memory. RareIQ
does not return them in the destination API or accept them through Studio X.
Do not commit credentials to Git.

## Exact OBS route verification

The public app token can verify the channel, but it cannot prove that OBS holds
that channel's stream key. Exact route verification is therefore optional and
requires a broadcaster user access token with the
`channel:read:stream_key` scope:

```powershell
$env:RAREIQ_TWITCH_USER_ACCESS_TOKEN = "your broadcaster user access token"
```

When that token is present, RareIQ validates its client ID, channel login, user
ID, scope, and expiry. It then reads OBS's active stream-service settings and
compares the OBS and Twitch keys in memory using a constant-time comparison.
Neither key, the user token, nor a reusable fingerprint is returned, logged, or
persisted by this connector. A custom Twitch ingest URL is accepted only when
its host matches Twitch's documented ingest domains.

## Truthful readiness boundary

A successful check may mark Twitch **Connected**, which means the Twitch API
token and configured public channel were verified. RareIQ intentionally keeps
the destination below **Ready** until the OBS-to-Twitch route can be verified
independently. With exact route verification configured, the same destination
may advance to **Ready** while offline and **Live verified** only when OBS is
streaming and Twitch simultaneously reports the configured channel live.

The connector fails closed when authentication, token validation, channel
lookup, stream lookup, or response validation fails. Status snapshots never
perform network I/O; only an explicit destination refresh contacts Twitch.
