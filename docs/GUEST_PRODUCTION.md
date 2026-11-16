# Guest productions in Producer, Please

## Current checkpoint — November 15, 2026

The studio can invite guests into one shared room, receive their camera,
microphone and shared screen/game window, prepare a composition, and take it to
the separate Studio Output browser window. This is a studio-core capability;
RareIQ remains the optional card add-on.

Real Chromium peer connections have been exercised locally with generated video
and audio. This is not yet a verified internet service, mobile-device certification,
OBS receipt test, or a live platform broadcast. No stream or recording was started.

## Producer workflow

Owner-confirmed setup: the PC runs production and each guest receives a separate
private invitation. For now, development and guest testing use localhost on that
PC. Domain purchase and internet hosting are deferred. Localhost links do not
reach other computers or phones; multi-device LAN capture needs a separately
configured secure local address. No network binding or public ingress is enabled
by this decision.

1. Open the studio and choose **Guests**. The Green room tool also lives in
   **Session tools** and can be moved like other tools. Panels grow with content.
2. Create an invitation and copy its private link. The secret link is shown only
   when created; dismiss it after sharing it with the intended person. For local
   testing, choose **Open guest tab** on this PC. Each guest needs a separate link.
3. Guests choose their devices and explicitly enable camera, mic or screen sharing.
   Their enabled feeds can be previewed by the producer while they wait.
4. **Admit guest** allows conversation in the room. It does not change Program.
   Choose **Listen to room** to monitor admitted guests; use headphones.
5. Select guest sources and local cameras to build Preview. Choose Automatic,
   Grid or Spotlight and a Cut, Fade, Slide or Zoom transition.
6. Open **Studio Output** and wait for it to receive the selected guest feeds.
   **Take Preview** moves that mix to Program. This does not start an encoder stream.
7. **Add my microphone** explicitly captures the producer mic and adds it as its
   own source. Select and take it if it should be heard on Program.
8. Use **Audio on Program** on each guest card to mute their microphone or screen
   sound independently. You can prepare this while they wait or change it mid-shot.
   Their capture and backstage conversation stay unchanged; guests see a notice.
9. Review **Recent activity** for invitations, admission/removal, audio settings and Program events.
   Requested changes and output-render confirmations are separate evidence.

Removing a guest, closing the room or losing their connection clears that guest
from Preview and Program. Reconnection needs another explicit selection/take.
Leaving stops the guest's camera, mic and screen, including permission requests
that finish after Leave. Invitation revocation also removes its connected guest.

## Audio and output

Preview monitors are muted. Program includes the microphone of each selected
guest once, even if both their camera and screen are selected. Screen audio is
included only with that selected screen and only when the browser supplied it.
Producer Program mute settings suppress the selected audio channel without stopping
its borrowed guest track. Unmute restores it when selected and available. Settings
survive a guest reconnect; a new guest starts unmuted. Activity records the setting,
not an additional renderer-confirmed mute receipt.
Conversation returns exclude the recipient's own audio and all waiting guests.

The room currently allows six participant slots and six selected composition
sources. A producer microphone uses one participant slot. This browser mesh has
bounded peer counts; bandwidth/CPU limits still need real multi-device testing.

Use the clean `/output/studio` browser source in OBS for the composed production.
OBS remains the external encoder. Browser rendering is not proof of platform
delivery or recording. The existing local-camera replay cannot capture a guest
composition; its Save action rejects such a mix instead of exporting the wrong shot.

## Voice, gestures and direction

Custom voice phrases use the studio's existing guarded production actions and
Windows speech recognizer. Edit while disarmed, then practice before arming.
Rules do not grant shell access, arbitrary HTTP requests or unlimited automation.
Scenes with browser-only Spotify/soundboard actions require their on-screen TAKE
button; hands-free recall rejects them before changing Program.

The experimental Hands-free camera tool uses a fixed, already-running studio
camera and local pinned vision models. It never opens another camera itself or
sends frames to a cloud model. Start in practice, assign gestures or calibrate
distinct head directions, and explicitly allow Program changes. Looking toward a
camera is estimated from head direction; this is not eye tracking. Confidence,
dwell, neutral return and cooldown guards apply. Tracking loss, manual switching,
SAFE, tab hiding and Stop revoke automated switching.

Pinned models/runtime can be installed with `tools/setup_production_vision.py`.
They live under `F:\Caches\ProducerPlease\vision`, outside source control. Real
lighting, occlusion, calibration and camera ownership still need hardware practice.

## Audience welcomes

Audience tools save welcome rules, provide a private animation preview, and send
authorized events to a separate graphics layer. Alerts start paused after a host
restart. The optional Twitch chat observer connects only after the local producer
clicks Connect and host authorization is configured. It supports first chat this
audience session and featured participants' chat. Observed people can be featured
with one click. It does not send chat or treat a silent viewer as a new arrival.

Twitch was tested with simulated provider responses, not a real account connection.
It requires the existing host Twitch client/channel settings and a broadcaster-owned
user token with `user:read:chat`. No token is accepted through the browser panel.
YouTube also connects explicitly from the production host, using the existing
host client ID, client secret, refresh token and channel ID. It verifies channel
ownership and requires exactly one active live chat. Initial history and recovery
backlogs are discarded; polling honors the provider interval with a 10-second
minimum and consumes API quota. A paused rule or disconnected source cannot
pretend to be ready. No chat messages are sent and no broadcast is created.

Kick has a simulated-provider-tested signed-event receiver, but the main app
does not mount its public endpoint. Its panel explains that setup is required.
An approved HTTPS event address, dashboard callback registration, existing owned
subscription and a credential-owner handoff are prerequisites. No webhook is
registered or deployed by this implementation. Verification checks raw-body RSA
signatures, source channel, app/subscription, event age, replay and current scope.
Failed verification never enters graphics. Public guest ingress does not accept
Kick event traffic.

All three provider integrations were tested offline, not against real accounts.
Follows and subscriptions remain pending; their rules wait for a supported
connection. No purchase or entitlement is inferred.

## Remote access and accountability

Guests use a browser; they do not need a desktop client for camera/mic access.
Screen-sharing availability depends on the browser/device. Phone screen sharing is
not promised. HTTPS is required away from localhost, and remote networks may need
a TURN relay. See [Guest ingress](GUEST_INGRESS.md) for the prepared, inactive
guest-only hosting boundary. Do not expose the unrestricted operator app through
a public loopback proxy. Public hosting, domain/TLS, relay and two-network tests are
separate approval/configuration work; no listener or firewall was activated here.

Invited guests are capability sessions, not verified personal accounts. Display
names are unverified. Activity records distinguish guest sessions, local/paired
operators, voice/gesture origins and the output renderer. Verified multi-producer
login remains blocked on the separate StackThis identity registration and callback
contract; guest invitations do not bypass it or enable RareIQ billing.

## Reproducible local evidence

- `tools/qa_greenroom_fixture.py NEW_F_DIRECTORY [PORT]` serves an isolated loopback
  fixture, blocks unrelated mutation/read paths and never starts hardware lifespan.
- `tools/qa_greenroom_media.cjs ABSOLUTE_EVIDENCE_DIRECTORY` checks two guests,
  camera/screen mixtures, audio isolation, transitions and removal on fixture 8768.
- `tests/browser/greenroom_host_audio.ui.cjs ABSOLUTE_EVIDENCE_DIRECTORY` measures
  actual return-audio frequencies with generated tones and checks host-mic cleanup.
- `tools/qa_guest_studio_ui.cjs ABSOLUTE_EVIDENCE_DIRECTORY` checks the complete
  running studio and guest pages on fixture 8769, dark/light at 390, 960, 1920 and
  3840 widths. Deliberately blocked legacy fixture reads are recorded separately.
- Canonical source gate: `.venv\Scripts\python.exe -B tools\release_check.py --require-node`.

Guest links, bearer tokens, account identifiers, local settings, captured media,
model binaries and runtime databases must stay out of Git and diagnostic exports.
