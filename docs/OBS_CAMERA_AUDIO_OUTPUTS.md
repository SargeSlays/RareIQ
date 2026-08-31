# RareIQ camera and soundboard outputs

RareIQ owns the physical cameras. OBS consumes Browser Sources from RareIQ; do
not open the same hardware as an OBS Video Capture Device. This implementation
does not install a Windows virtual-camera or virtual-audio-cable driver.

## Ready-made OBS scenes

The Production page's Preview Plan / Create in OBS action now creates these
additional sources alongside the existing six production scenes:

| OBS scene | Browser-source URL |
| --- | --- |
| RareIQ Scan Camera | `http://127.0.0.1:9040/output/camera/scan` |
| RareIQ Camera 1–4 | `http://127.0.0.1:9040/output/camera/1` through `/4` |
| RareIQ All Cameras | `http://127.0.0.1:9040/output/camera/all` |
| RareIQ Soundboard | `http://127.0.0.1:9040/output/soundboard` |
| RareIQ Set Chase | `http://127.0.0.1:9040/overlay/set-chase` |

Use 1920×1080 browser dimensions for camera/audio sources. Set Chase uses
**1280×320**; setup places this silent strip bottom-center with a safe margin,
without enlarging beyond native size. It scales down for smaller/portrait
canvases, preserving the complete strip. Existing nonempty scenes are never
repositioned. Creating an OBS source does not publish the Set Chase draft.

**Broadcast → Setup → Browser source library** lists all 14 clean sources,
their dimensions, placement, audio behavior, and individual Copy URL buttons.
The source library and OBS plan use one catalog, including the Set Chase editor
link. The offline plan says **Connect to inspect** until OBS can be authenticated;
it does not assume existing scenes are safe to create or overwrite.

The scan source follows the active recognition
camera; numbered sources follow their assigned slot. The quad source displays
all four slots. Complete frames are contained, not cropped. Unassigned/stale
cameras output black. `?preview=1` adds status labels for diagnostics; omit it in OBS.

Camera pages use a binary WebSocket stream so simultaneous outputs do not exhaust
the browser's HTTP connection pool. Capture ownership stays in CameraManager;
clean scan JPEGs are encoded on demand and cached across subscribers. Scan output
is capped at 1920 pixels wide, preserving aspect ratio. Secondary cameras currently
use the existing efficient 1280×720, 15-fps staging capture policy; choosing a 1080p
OBS canvas does not increase their native capture resolution.

## Soundboard audio

1. In RareIQ **Sounds**, enable **Send soundboard to OBS**.
   Routing is saved in RareIQ's configuration and shared across browsers; a fresh
   page inherits the saved setting. The controls report a save failure instead of
   pretending a browser-only change was persisted.
2. In OBS, use the shared **RareIQ Soundboard** scene as an existing source inside
   the scenes that should receive audio. Do not create several independent copies
   of the audio browser input in the same output scene.
3. Its **RareIQ Soundboard Audio** browser input must have **Control audio via OBS**
   enabled. Keep **Shutdown source when not visible** and automatic source refresh
   disabled. Bootstrap sets these properties.
4. Turn off **Monitor on this computer** if OBS also captures Desktop Audio;
   otherwise the same sound can arrive twice. The dedicated mixer input has its
   own OBS volume/mute/track routing. Camera feeds themselves carry no audio.

Queue, layered playback, master volume and Stop All are mirrored to the digital
output. Receiver disconnection silences its players. Closing a controller stops
its sounds; a four-second lease expires them if the controller disappears without
sending a stop. Autoplay in a normal browser preview may require **Enable preview
audio**; use the clean URL in OBS.

On this workstation, output is enabled and local monitoring is disabled. The shared
audio scene is linked into all 12 RareIQ visual scenes, including Multi Card,
Replay, Graphics and Production Screen. Existing unrelated scenes were not changed.
Future fresh bootstrap installs can run the verification command with `--wire-audio`
or add that scene using OBS's Add Existing flow. Reload already-open RareIQ pages
once after upgrading to load the shared routing controls.

## Verification and remaining hardware checks

- **Broadcast → Setup → Check sources** takes a read-only configuration snapshot
  of the 14 dedicated RareIQ scenes. It checks for missing/duplicate inputs,
  Browser Source type, exact clean URL, native dimensions, OBS audio routing,
  shutdown/refresh settings, visibility and cropping. It never creates, repairs,
  refreshes or moves sources, switches scenes, plays audio, or starts output.
  A renamed input is recognized by its clean URL; namespace suffixes from setup
  are supported. Complex scenes are marked Not checked rather than guessed.
- The report distinguishes **Configured**, **Review setup**, **Missing** and
  **Not checked**, with a snapshot time. A disconnect or incomplete inspection
  clears previous green results. Saving OBS settings or running setup invalidates
  the displayed snapshot. Run it again after manual OBS changes.
- This is **not** an end-to-end media test: a correct URL cannot prove that a
  camera has a fresh picture, an overlay is published, or audio is audible.
  It checks dedicated scenes, not every nested source in custom operator scenes.
  Check actual picture/audio and final-scene composition separately before a show.
- `tools/preview_obs_sources.py` serves disconnected, configured, warning and
  request-failure visual fixtures at `http://127.0.0.1:9056`. It uses the shipped
  markup, styles and controller without contacting OBS or production APIs.
  Browser review covered 1080p, 4K, narrow windows and both themes. The workstation's
  real OBS was closed during this audit feature's verification; the production
  report correctly showed all 14 sources as Not checked.
- `tools/verify_broadcast_outputs.py` uses the managed-source catalog, captures
  scan/quad screenshots, and checks the soundboard's real OBS audio meter off-air.
  It preserves Program selection and restores Studio Mode. It refuses to run while
  streaming/recording. `--wire-audio` adds the shared audio scene to all RareIQ visual
  scenes idempotently. A brief, low-volume saved sound is used, stopped
  in cleanup, and any temporary Program audio link is removed afterward.
- Camera 1 / Insta360 Link was verified simultaneously in RareIQ and OBS, with no
  diagnostic text or scan boxes in the clean output.
- Slots 2–4 were unassigned. Their source routes, quad positions, lease cleanup,
  and multiplexing were tested; four actual devices still require a hardware test.
- Real browser pad playback and Stop All passed with local monitoring disabled.
  OBS's dedicated soundboard meter registered nonzero audio. No stream/recording
  was started.

OBS reference: [Browser Source documentation](https://obsproject.com/kb/browser-source).
