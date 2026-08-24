# RareIQ Mobile Access

RareIQ mobile access is an opt-in trusted-LAN mode. The default remains
loopback-only, so another device cannot reach Studio X unless an operator
explicitly enables authenticated LAN binding.

## Security boundary

- LAN mode binds RareIQ to the workstation's wildcard network interface.
- Every non-loopback browser must pair before it can load Studio X, static
  assets, APIs, streams, or WebSockets.
- Pairing uses a token of at least 24 characters from the ignored local secrets
  file or `RAREIQ_REMOTE_ACCESS_TOKEN`.
- The browser receives an HttpOnly, SameSite=Strict session cookie derived from
  the token and current server session. Restarting RareIQ invalidates it.
- The token is never accepted from a URL query string and is never written into
  frontend storage.
- Local desktop access remains available without pairing.

LAN mode authenticates clients but does not add TLS. Use it only on a trusted
private network. Do not port-forward RareIQ, expose it directly to the internet,
or use it on an untrusted public Wi-Fi network.

## Configure a pairing token

Generate a strong token locally:

```powershell
.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
```

Add the generated value to the ignored `rareiq_secrets.json` file:

```json
{
  "remote_access_token": "paste-the-generated-token-here"
}
```

Keep any existing keys in that file. Never add the real secrets file to Git.

## Start or restart in LAN mode

```powershell
.venv\Scripts\python.exe -B tools\server_control.py start --lan --port 8765
```

For an already managed server:

```powershell
.venv\Scripts\python.exe -B tools\server_control.py restart --lan --port 8765
```

Find the workstation's private IPv4 address with `ipconfig`, then open this URL
on the phone while both devices are on the same trusted network:

```text
http://WORKSTATION-IP:8765/control
```

RareIQ redirects an unpaired device to the pairing screen. Enter the token once;
the session remains valid for up to 12 hours or until the server restarts.

## Return to local-only mode

```powershell
.venv\Scripts\python.exe -B tools\server_control.py restart --local
```

This restores the `127.0.0.1` binding. It does not delete or reveal the stored
pairing token.
