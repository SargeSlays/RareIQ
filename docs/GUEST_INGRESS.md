# Guest-only ingress — integrated, disabled by default

`rareiq.web.guest_ingress.GuestOnlyIngress` wraps the existing ASGI application.
It permits the exact public guest page/assets, POST join/leave, authenticated GET/POST chat, and the guest
publishing/viewing WebSockets (`/guest/ws`, `/guest/view/ws`). All operator APIs, output sockets, documentation, arbitrary static
files and other paths are rejected before reaching the studio app.

The wrapper uses the **same app object and GreenroomHub in the same process**.
Starting another `rareiq.web.server` process would split signaling and is not a
supported deployment. Startup/shutdown belongs to the primary operator listener;
the guest wrapper acknowledges lifespan events without forwarding them.

## Host configuration and lifecycle

The existing studio lifespan now owns `GuestIngressLifecycle`. Nothing starts
when `PRODUCER_GUEST_INGRESS_PORT` is absent or empty. This checkpoint did not set
environment values or activate any listener, proxy, firewall rule or hosting.

To enable this later, configure the following **on the studio host process**, then
use the existing normal studio launcher. Do not launch another app process.

| Setting | Required value |
| --- | --- |
| `PRODUCER_GUEST_INGRESS_PORT` | Explicit unused integer port from 1024 through 65535, different from the operator port; for example `8766`. |
| `PRODUCER_GUEST_HTTPS_ORIGIN` | Exact HTTPS guest origin, such as `https://guests.example.test`; no path, query or fragment. The example is not a deployed address. |
| `RAREIQ_PORT` | Actual operator port; defaults to `8765`. Do not override the primary bind port separately with an unrelated Uvicorn command. |

The shared `GreenroomNetwork` still owns optional `PRODUCER_GUEST_TURN_URLS` and
`PRODUCER_GUEST_TURN_SECRET`. No relay is created by these settings; a separately
configured relay and its host secret are required when network traversal needs it.

After initializing its shared services, the studio starts the optional secondary
listener in the same process and event loop, with the exact `_app` object. The
secondary listener has no additional application lifespan or process signal
handler. Its startup readiness wait is bounded to three seconds; a failed bind,
early exit, invalid configuration or timeout is reported as unavailable without
terminating the main studio. There is no automatic retry loop. Shutdown stops the
secondary listener before closing studio dependencies, with a bounded graceful
wait and cleanup of only its own listener sockets and request tasks.

Operator greenroom state exposes `connection.guest_ingress`, including `state`,
`reason`, `available`, `bind`, `port` and `public_verified`. States include
`disabled`, `starting`, `listening`, `unavailable` and `stopped`. **Listening means
only that the local guest-only listener started.** `public_verified` remains false;
it is not evidence that HTTPS, proxy routing, TURN or external guests work.

`create_guest_listener(shared_app, public_origin=..., port=..., operator_port=...)`
remains an inactive factory for embedding/testing. The integrated lifecycle owns
its production use. Do not call it from another process, enable reload/workers,
or add another independently imported studio app.

The listener factory binds only to `127.0.0.1`, disables proxy-header trust and
access logging, limits WebSocket frames/queues and connection concurrency, and
disables duplicate lifespan handling. It does not configure or start HTTPS,
a reverse proxy, a tunnel, TURN, a firewall rule or an external listener.

## Required proxy contract

- Terminate valid HTTPS at the exact configured `PRODUCER_GUEST_HTTPS_ORIGIN`.
  Forward guest HTTP/WebSocket traffic only to the dedicated loopback guest port,
  never to the operator port. The proxy and OS must prevent alternate access to
  the operator listener.
- Preserve the canonical Host and browser Origin headers. Host must exactly match
  the configured lowercase authority, including a configured port. POST and
  WebSocket requests require the exact HTTPS Origin. The wrapper does not derive
  trusted identity or origin from Forwarded/X-Forwarded headers.
- Preserve the original raw path without decoding/re-encoding, slash collapsing,
  path rewriting, or stripping a prefix. The wrapper rejects encoded paths,
  traversal, backslashes, noncanonical aliases and nonempty ASGI root paths. It
  cannot inspect an original path already normalized by an upstream proxy.
- Apply edge connection/body/time limits and per-client rate limiting. The wrapper
  deliberately supplies one non-operator client identity (`guest-ingress`) to the
  shared app; it does not trust forwarded client IPs. The existing join limiter
  therefore shares its 20-per-minute bucket across this ingress.
- Guest invitations stay in URL fragments and guest authentication stays in the
  join body/WebSocket authentication message. Leave and chat accept a guest Bearer
  session token. Cookies and inherited operator principals/session state are
  removed. Query parameters are denied except a bounded `v=` asset version and chat GET
  `channel=room|private` with optional 32-hex `room_id`. Guest recipient/author
  fields are never forwarded from query parameters.

The wrapper buffers at most 8 KiB for join or chat POST within five seconds and
rejects bodies on every other HTTP route. Chat POST requires JSON; chat GET and
POST are the only supported chat methods. The shared service enforces the
1,000-character text bound, sender rate limit and current invitation access. Actual invitation validation, admission, revocation,
media permissions, signaling schemas and source selection remain owned by the
existing GreenroomHub/service. Model or camera frames do not travel through this
guest ingress.

## Verification boundary

In-memory ASGI tests exercise allowed routes and methods, strict Host/Origin,
path/query/header/body rejection, cookie/principal stripping, WebSocket isolation,
and shared hub/lifespan behavior. Fake-listener tests cover disabled defaults,
invalid configuration, single startup, bind failure/SystemExit isolation, startup
timeout, unexpected exit, bounded shutdown and cleanup of secondary requests.
No real listener or public service was started by these tests.
Real proxy/TLS routing, socket upgrades, network traversal, TURN and remote media
must be tested separately before remote hosting can be advertised as verified.

Room viewing reuses the invitation session in its first WebSocket authentication
message. It carries only a safe roster and admitted guest camera subscriptions;
it grants no producer controls. Both sockets share revocation and origin checks.
