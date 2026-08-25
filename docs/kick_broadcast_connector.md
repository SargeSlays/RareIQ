# Kick broadcast connector

RareIQ's Kick adapter is a read-only monitor for one explicitly configured
channel. It verifies the authorized user and channel, checks Kick's own live
state, and privately proves that OBS has the exact stream URL and key returned
for that channel. It does not change channel metadata, start broadcasts, send
chat, subscribe to events, or rotate stream keys.

## Local configuration

Create a Kick developer application and complete Kick's OAuth 2.1 authorization
code flow with PKCE. Request only these scopes:

`user:read channel:read streamkey:read`

Store the returned refresh token in the local RareIQ server environment:

```powershell
$env:RAREIQ_KICK_CLIENT_ID = "your Kick application client ID"
$env:RAREIQ_KICK_CLIENT_SECRET = "your Kick application client secret"
$env:RAREIQ_KICK_REFRESH_TOKEN = "your authorized user refresh token"
$env:RAREIQ_KICK_CHANNEL_SLUG = "your-channel-slug"
```

Restart RareIQ, open **Broadcast → Destinations**, and use **Check status**.
RareIQ does not accept these values through Studio X or return them from its
APIs. Do not commit credentials to Git.

## Verification model

The connector introspects the user access token and requires all three scopes.
It then verifies that the authenticated user's ID owns the configured channel
slug. Kick's private stream URL and key are compared in memory with the OBS
stream-service settings; neither value is returned, logged, hashed for display,
or persisted by this connector.

The destination becomes **Ready** only after both the server URL and stream key
match. **Live verified** additionally requires OBS to be streaming while Kick
reports that same channel live. OAuth errors, missing scopes, identity
mismatches, malformed responses, and partial route matches all fail closed.

Kick may rotate refresh tokens. RareIQ uses a newly returned refresh token only
in memory for the running process; deployment owners remain responsible for
secure durable token management outside Studio X.
