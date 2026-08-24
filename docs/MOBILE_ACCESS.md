# RareIQ Mobile Access

RareIQ mobile access is an opt-in trusted-LAN mode. The default remains
loopback-only, so another device cannot reach Studio X unless an operator
explicitly enables authenticated LAN binding.

Studio X Settings includes a read-only **Phone & Tablet Connection** card. It
reports local-only versus authenticated-LAN mode, pairing readiness, and safe
LAN URLs when available. It never displays the pairing token and cannot change
the server binding.

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
- Repeated failed pairing attempts are throttled per client before another token
  can be tried.
- Local desktop access remains available without pairing.

LAN mode authenticates clients but does not add TLS. Use it only on a trusted
private network. Do not port-forward RareIQ, expose it directly to the internet,
or use it on an untrusted public Wi-Fi network.

## Configure a pairing token

Preview the setup first. This does not write a token:

```powershell
.venv\Scripts\python.exe -B tools\server_control.py mobile-setup --port 8765
```

Apply setup to generate and atomically store a strong token in the ignored
`rareiq_secrets.json` file:

```powershell
.venv\Scripts\python.exe -B tools\server_control.py mobile-setup --port 8765 --apply
```

The command prints a newly generated pairing token once so it can be entered on
the phone. Existing credentials in the file are preserved. Running setup again
does not replace an existing token; use `--rotate` only when intentionally
invalidating previously paired devices. Never add the real secrets file to Git.

Check configuration and discover current private-LAN addresses without showing
the token:

```powershell
.venv\Scripts\python.exe -B tools\server_control.py mobile-status
```

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

## Add Studio X to a phone or tablet home screen

After pairing succeeds, use the browser's **Add to Home Screen** or **Install**
action. RareIQ opens in a standalone app window and keeps using the same LAN
address and pairing cookie.

RareIQ intentionally does not register an offline service worker. The camera,
recognition pipeline, and operator state require a live connection to the
RareIQ workstation. If the workstation or LAN connection is unavailable, the
installed shortcut cannot operate until that connection returns.

## Return to local-only mode

```powershell
.venv\Scripts\python.exe -B tools\server_control.py restart --local
```

This restores the `127.0.0.1` binding. It does not delete or reveal the stored
pairing token.
