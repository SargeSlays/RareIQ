# Producer, Please desktop checkpoint — November 18, 2026

Producer, Please now has a Windows Electron shell and a native output/encoding
path that does not require OBS. The complete path has been exercised locally
with generated media and a local encoded file. Real destination delivery and
physical capture acceptance remain untested for this checkpoint. Existing OBS
workflows remain available; RareIQ's separate card product is not renamed or
replaced by this desktop work.

## Local installation and storage

This is a **local development build**, not a portable installer or public release.
The Electron executable is under `F:\Apps\ProducerPlease\builds`; the selected
executable is recorded in `F:\Apps\ProducerPlease\latest-build.json`. Its runtime
manifest still requires the existing RareIQ checkout on C: and that checkout's
`.venv\Scripts\python.exe`. Do not move or remove them and expect the desktop
build to continue working. The encoder worker and its extra Python packages are
copied into app resources, but the full backend/Python runtime is not bundled.

Desktop profile, browser state and logs default to
`F:\Users\<user>\AppData\ProducerPlease`; build/dependency caches use
`F:\Caches\ProducerPlease`. Rehearsal artifacts use named directories under
`F:\Temp\jonat`. The backend retains its configured storage locations; opening
the desktop app does not relocate existing scenes, card data or captures.
Windows' per-user Start Menu shortcut remains in its supported C: AppData
location. Existing Windows/runtime tools and the development checkout also
remain on C:; this checkpoint does not claim a universal relocation to F:.

## Broadcast setup and state

Open **Producer, Please** from the Windows Start Menu. The local app was launched
and visually inspected against the managed studio with no destination saved and
no transmission started. Use **Broadcast setup** in the studio header or app menu.

1. Open **Broadcast setup**, choose Twitch, YouTube, Kick or Custom, and enter the
   stream key from that platform's dashboard. Twitch has a secure server preset;
   YouTube, Kick and Custom require the dashboard's server URL as well. The native
   encoder requires RTMPS. Saving settings does not start transmission.
2. Select the output format and **Prepare output**. The separate Studio Output
   window owns the actual Program picture and public audio. Review any browser
   sources there, then close review before starting.
3. Choose **Start broadcast** and explicitly confirm the named destination.
   Local sending/encoding status is not proof of platform receipt. Confirm the
   picture, audio and delivery in the platform's own dashboard.
4. Use **Stop broadcast** before closing. If encoder shutdown is not confirmed,
   the desktop keeps the application open rather than discarding that ownership.

There is no platform OAuth login, connected-account client, client-ID setup or
verified online operator identity in this checkpoint. Destination names/keys are
manual configuration. Activity is attributed to a local desktop operator, not an
authenticated Twitch/YouTube/Kick account. No real platform credentials or account
changes were used during acceptance.

Windows account encryption (Electron safeStorage/DPAPI) protects the saved server
URL and stream key. Public status never returns saved secrets; plaintext keys do
not enter command-line arguments, renderer status, activity logs or test evidence.
If encryption is unavailable, saving fails rather than falling back to plaintext.

## Runtime and safety boundaries

- The backend controller starts or reuses the managed loopback server. An existing
  browser-mode server is reused without taking shutdown ownership; native
  preparation then explains `desktop_mode_required` rather than restarting it.
- Desktop startup skips eager boot/camera discovery, OCR warmup, catalog freshness,
  instant replay and auto-clip lifespan starts. This does not complete the broader
  removal of constructor-owned card services from the current backend.
- Native preflight checks current source availability and a fresh rendered receipt
  from the exact output peer being captured, at the same Program generation. It
  does not use another output window's readiness or require OBS to be connected.
- Native capture uses that output's compositor and public audio. It excludes
  nested/private/backstage frames and does not capture system/desktop audio by
  default. The muted local output window still supplies its approved audio tap.
  Review mode, stale output, receiver replacement and audio/capture failures block
  or stop encoding. Camera, microphone and screen permissions remain explicit.
- The backend tracks the Main process's encoding ownership. A missed heartbeat
  never makes a live or uninspectable owner idle; confirmed process exit clears
  stale ownership. Main clears its claim after stopping its encoder.
- App close only considers stopping the backend it started, with matching process
  identity and a consumed private ownership receipt. Active production, recording,
  native encoding, connected output/guest clients or uncertain state preserve it.
  The existing OBS idle check remains conservative even though native preflight
  does not require OBS. Reused or unmanaged servers are never force-killed.
- RTMPS resolves and checks public addresses, pins the checked destination, and
  verifies the certificate chain and hostname through an owned TLS transport.
  Wrong-host and untrusted-CA failures occur before media delivery. The loopback
  transport seam is limited to the encoder's own process. No automatic reconnect
  or platform-live verification is claimed.

The encoder selects a codec using an actual generated-frame encode probe. NVENC
did not initialize successfully in this PC's current runtime, so software H.264
(`libx264`) is the verified path. GPU throughput and the underlying NVENC failure
cause have not been established. Output capture was exercised at 1280×720,
1920×1080 and 720×1280; full native encoding acceptance below is specifically 720p.

## Acceptance evidence

All paths below are local evidence, excluded from source/release archives. Test
certificates, keys and profiles are synthetic and must not become production
configuration. Directory names alone do not indicate a passing result.

| Scope | Observed result | Evidence under `F:\Temp\jonat` |
| --- | --- | --- |
| Native shell and protected settings | Real window, isolated renderer bridge, DPAPI round trip, synthetic destination saved without plaintext key exposure; no account connection | `ProducerPlease-desktop-20261118/native-acceptance/results.json` |
| Output capture and audio isolation | Three output sizes; monotonic timestamps; volume/mute/pause/seek/loop; public Soundboard; private frames excluded; review blocks capture | `RareIQ-output-capture-qa-20261118/{1280x720,1920x1080,720x1280}/results.json` |
| Complete native chain | Real asset import → Preview/Take → exact output peer → preflight → ownership → compositor/audio → PyAV local FLV. 6.153 s, 184 H.264 1280×720 frames, 29.9041 fps, AAC 48 kHz stereo; 440 Hz tone detected; zero reported capture/encoder drops | `ProducerPlease-native-full-20261118-05/results.json`, `native-program.flv`, `ffprobe.json` |
| Background rendering and stop | Image/title Take while output was minimized appears in decoded video; ownership cleared while Main was still alive; owned test processes closed | Same full-chain directory, `video.png` and `second-source.png` |
| Clean picture | An injected opaque preparation notice is excluded before the first captured frame; preparation controls return after Stop; decoded pictures inspected | Same full-chain directory, `cleanControlsExcluded` and `preparationUiRestored` in `results.json` |
| Verified local RTMPS | Trusted localhost certificate: received/decoded 90 H.264 frames and stereo AAC. Wrong hostname and wrong CA: zero received media bytes. Passing valid-certificate repeat | `ProducerPlease-encoder-RTMPS-serialized-20261118/tls-results.json`; `ProducerPlease-encoder-RTMPS-repeat-20261118/repeat-results.json` |

The full-chain rehearsal creates its own isolated server state before application
import, disables constructor workers, and blocks external network/DNS and physical
capture. It replaces only the final destination with a local file; production
asset, composition, signaling, preflight, capture and encoder code remain in use.
The separate TLS rehearsal uses a local receiver and synthetic media, not a real
platform. Earlier failed TLS attempts remain preserved as diagnostic history and
are not release evidence.

## Remaining acceptance

Real Twitch/YouTube/Kick/custom destination receipt, platform-specific ingest
compatibility, listener-quality A/V sync, physical cameras/microphones/screen capture,
driver recovery, prolonged production, and network-loss recovery require separate
authorized checks. Full 1080p/portrait encoding endurance, reliable hardware encoding,
a self-contained runtime, signed installation/update/uninstall and clean-machine
acceptance are not established. Local file capture and a passing TLS fixture must
not be described as a live platform broadcast or a production-ready release.

## Reproduce the isolated full-chain check

Use the development Python environment, Node with Playwright available, the cached
Electron executable, and a **new** F: evidence directory:

```powershell
node desktop/tests/standalone-rehearsal.cjs F:/Temp/jonat/ProducerPlease-native-full-NEW F:/Caches/ProducerPlease/desktop-dependencies/node_modules/electron/dist/electron.exe
```

The harness starts and closes only its own loopback fixture and Electron process.
It permits the native status/preflight and ownership endpoints, but explicitly
blocks shutdown endpoints. It never supplies a real network destination. Canonical
release-gate results for the final checkpoint are recorded separately in
[RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md).
