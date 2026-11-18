# Producer, Please desktop checkpoint — November 18, 2026

Producer, Please now has a Windows Electron shell and a native output/encoding
path that does not require OBS. The complete path has been exercised locally
with generated media and a local encoded file. Real destination delivery and
physical capture acceptance remain untested for this checkpoint. Existing OBS
workflows remain available; RareIQ's separate card product is not renamed or
replaced by this desktop work.

## Local installation and storage

There are now **two private build types**, neither a public installer release.

| Build | Runtime and current entry point |
| --- | --- |
| Primary development app | The existing Start Menu entry and `F:\Apps\ProducerPlease\latest-build.json` remain unchanged. This thin shell requires the C: RareIQ checkout and its `.venv\Scripts\python.exe`. Keep those in place. |
| Bundled runtime candidate | `F:\Apps\ProducerPlease\latest-bundled-build.json` identifies a separate build with embedded Python, approved backend source/static assets, encoder and dependencies in its own resources. Its tested backend does not require the development checkout or Python environment. Packaged Program has local acceptance; clean-machine acceptance remains separate. |

Desktop profile, browser state and logs default to
`F:\Users\<user>\AppData\ProducerPlease`; build/dependency caches use
`F:\Caches\ProducerPlease`. Rehearsal artifacts use named directories under
`F:\Temp\jonat`. The backend retains its configured storage locations; opening
the desktop app does not relocate existing scenes, card data or captures.
Windows' per-user Start Menu shortcut remains in its supported C: AppData
location. Existing Windows/runtime tools and the development checkout also
remain on C:; this checkpoint does not claim a universal relocation to F:.

## November 18, 2026 — Private standalone preview

Launching the bundled executable with `--preview` selects
`F:\Users\<user>\AppData\ProducerPleasePreview` and loopback port **8767**.
The preview banner identifies this separate profile. It does not migrate scenes,
catalogs, captures, accounts or destination keys from the primary app. The normal
port 8765 studio and its shortcut are preserved. **Producer, Please - Standalone
Preview** is installed in the Windows Start Menu and was opened and visually
inspected on port 8767. Its new profile has no copied accounts or destination keys.

The resources manifest uses relative paths, resolved and checked against the real
resources directory, including Windows junctions. Resources are treated as read-only;
the preview's backend config, databases, captures and logs belong under its F:
profile. Defaults are created there before backend imports. Existing profile values
are preserved, and startup does not read configuration or credentials from the
developer checkout. Camera selection remains an explicit operator action: desktop
launch disables the older automatic boot/discovery path.

The private candidate pins **CPython 3.13.12 amd64**, matching the existing native
package ABI, from the official
[`python-3.13.12-embed-amd64.zip`](https://www.python.org/ftp/python/3.13.12/python-3.13.12-embed-amd64.zip)
archive. Packaging checks SHA-256
`76f238f606250c87c6beac75dccd35ee99070a13490555936abb6cb64ecce3d0`.
This is a compatibility pin, not a claim to include the newest Python patch.
Updating the interpreter requires another dependency/encoding acceptance pass.

The candidate includes **48 dependency distributions**, FFmpeg binaries, approved
default seeds and an inventory of copied source/package files. The backend builder reads
the staged Git source tree through an allowlist; it does not package the dirty
working directory, operator JSON, secrets, captures, catalogs or user model/cache
directories. Models supplied as stock wheel assets are a distinct part of those
third-party packages and may be included. Python licenses, package metadata/license
files and binary notices remain with the build. Their presence is not a legal
determination; redistribution/license review remains a public-release gate.

## Bundled candidate acceptance and remaining proof

Candidate 02 passed these separate checks under
`F:\Temp\jonat\ProducerPlease-bundled-20261118`:

| Scope | Observed result | Evidence |
| --- | --- | --- |
| Actual bundled backend, port 8767 | Bundled executable/PID verified; 569 probed module paths and app/server/controller origins inside resources despite deliberately invalid `PYTHONHOME`/`PYTHONPATH`; 14 profile files on F:; before/after resource hashes identical | `backend-acceptance02/results.json`, `import-paths.json`, resource hash files |
| Native packaged app, port 8770 | Actual EXE started its bundled backend; Studio/setup and source navigation worked without Take; protected storage available; owned test backend closed | `native-acceptance/results.json`, `bundled-studio.png`, `bundled-setup.png` |
| Bundled local encoder | Software H.264 encoded 90 generated frames and 144,000 audio samples into a local FLV; zero reported video/audio drops | `encoder-acceptance/results.json` and its synthetic FLV |

Backend acceptance used the actual controller and app, without mocked readiness.
Native encoding remained inactive; empty Program correctly reported `unassigned`
and `output_not_identified`. Normal quit retained the server because OBS was not
confirmed idle. Only the acceptance harness then terminated its newly owned test
process, after checking the exact identity, bundled executable, profile/port,
inactive session/recording/encoding and absence of clients. That QA-only cleanup
does not relax application quit. Port 8765 was not contacted by this check.

The first `backend-acceptance` directory is a failed harness probe: it incorrectly
required Python `aiortc`. Production WebRTC peers live in the browser; Python
provides signaling. The corrected probe checks dependencies against actual source
imports. Keep that failed attempt as diagnostic history, not candidate evidence.

Candidate 04 passed the complete packaged Program rehearsal with its actual
backend, app.asar production modules, embedded Python, encoder and FFmpeg. Generated
video/audio was imported through the real API and taken to Program; an image/title
Take changed decoded frames while the output was minimized. The local file contains
170 H.264 1280×720 frames over 5.685 seconds (29.9033 fps) with AAC 48 kHz stereo
and the generated 440 Hz tone. No dropped video/audio queues were reported.
An injected preparation notice stayed out of encoded pixels and returned after
Stop. Ownership cleared before the app exited; the owned test backend was closed.
Evidence: `native-program-acceptance04/results.json` and its `program` directory.

The isolated source gate passed **3533 Python tests and 592 JavaScript tests**;
see `release-gate.log`. The failed Program harness attempts remain preserved:
they exposed Electron-evaluate callback/require assumptions and the need to wait
for backend output acknowledgment before Take; readiness was never bypassed.
No real platform transmission, account changes or physical capture were performed.

The candidate also passed its real backend/import/resource checks after copying
the complete application folder to a different location, using isolated port 8771.
Evidence: `relocated-acceptance/results.json` (no resource changes). The local
evaluation archive is `F:\Apps\ProducerPlease\packages\ProducerPlease-standalone-preview-20261118-win64.zip`;
its ZIP integrity check passed and no operator configuration files are included.
This is a private preview folder/ZIP, not a signed installer or clean-machine claim.

## Broadcast setup and state

Open **Producer, Please** from the Windows Start Menu. The local app was launched
and visually inspected against the managed studio with no destination saved and
no transmission started. Use **Broadcast setup** in the studio header or app menu.

The three-step guide separates Program, clean output and destination readiness.
**Choose sources** opens the existing studio source library without selecting a
source, taking Preview or starting capture. Setup is hidden, preserving its draft;
reopen Broadcast setup to continue. **Add destination** moves to the saved-key form.
A changed output format requires preparing that format again. A securely saved
destination is not a verified connected account or proof of platform delivery.

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
driver recovery, prolonged production, and real-destination network-loss recovery require separate
authorized checks. Full 1080p/portrait encoding endurance, reliable hardware encoding,
signed installation/update/uninstall, runtime
updates, migration and clean-machine acceptance are not established. Public
redistribution also needs licensing review. Local file capture and a passing TLS fixture must
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

## November 18, 2026 — Explicit broadcast recovery

Broadcast setup now includes **View output**, which restores the existing trusted
clean-output window without changing Program, starting transmission or opening
browser review. During sending, use this control to inspect that same output.

If output or encoder failure stops transmission, setup shows recovery guidance
and the last safe codec/frame/audio counts. Restore unavailable sources or check
the destination/connection, prepare output when needed, then choose **Start
broadcast** and confirm again. There is no automatic restart or reconnect.
If shutdown or the studio ownership update is uncertain, **Stop broadcast** stays
available and Start/Prepare remain blocked. Keep the application open and retry
Stop; closing the window must not discard an unconfirmed encoder or ownership claim.

Actual packaged acceptance used generated imagery and two local FLVs: closing
the sending output stopped its real worker and released backend ownership;
counts remained visible (37 frames), no restart occurred, and a second explicit
confirmation started a new window/peer and encoded 44 frames. Both local files
decode as H.264 1280×720 and AAC 48 kHz stereo. Every owned test worker exited.
Settings View output was also exercised through its real bridge. Recovery message
screens in dark/light use simulated public statuses; the worker/output-loss test
uses actual packaged modules and backend receipts.

A separate local TLS receiver disconnect test stopped its real encoder worker,
then a new explicit attempt encoded 90 generated frames to a local file. The
disconnect reported the safe generic encoder failure; no more specific network
diagnosis is claimed. These local checks do not establish platform receipt,
physical devices, listener quality or prolonged network recovery.

Evidence: `F:/Temp/jonat/ProducerPlease-recovery-20261118/`:
`native-ui01/results.json`, `native-recovery01/recovery/recovery-results.json`,
`encoder03/results.json` and `release-gate.log`.
Accepted recovery build: `0.1.0-20261118105522739`. The separate Standalone Preview
shortcut points there after acceptance. An already-open preview keeps its earlier
build until closed/reopened; its profile and the primary studio are preserved.

## November 18, 2026 — Edit protected destinations

Use **Edit** beside a saved destination to correct its name, replace its stream
key, or enter another secure server address. Existing keys and server addresses
are never filled into the form or returned to Settings. Leave a field blank to
keep its saved value. Entering a server address requires a replacement key, so a
saved key cannot silently move to another server. The platform stays fixed during
editing; add a separate destination to use another platform. Cancel editing
restores the unfinished Add destination draft. Saving an edit restores that draft
too, and does not start transmission. Start stays disabled until editing finishes.

During pending/active transmission or uncertain ownership, destination mutations
are blocked in both Settings and Main. While a save/remove is awaiting persistence,
Main blocks Start and repeated mutations. The platform dashboard remains available
while sending. A failed save retains the edit and retry request ID; switching into
editing and back also preserves an ambiguous Add retry's request ID.

The packaged candidate `0.1.0-20261118110448557` passed real Settings/Windows
encryption acceptance with synthetic Twitch/YouTube profiles: rename kept the same
profile/key/server; Cancel restored the Add draft; server replacement without a
key changed nothing; an explicit replacement updated both. Private values were
checked only inside Main and never returned as status. Program generation and
sources did not change, encoding stayed inactive, and owned QA processes closed.
Dark/light layouts were inspected at 800×900, 1920×1080 and 3840×2160 with no
horizontal overflow. Existing 8765/8767 studios and real credentials were untouched.

Evidence: `F:/Temp/jonat/ProducerPlease-destination-edit-20261118/native02/results.json`
and the six `destination-edit-*.png` captures. `native01` is a failed harness attempt
that tried to fill Twitch's intentionally hidden server field; it closed its owned
backend and is retained as diagnostic evidence. This does not establish platform
login or receipt. Reopen the separate Standalone Preview entry to load this build.
