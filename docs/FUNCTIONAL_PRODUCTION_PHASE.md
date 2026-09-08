# Functional production phase: current checkpoint

September 8, 2026. Continue from the existing Producer, Please studio; RareIQ
remains the separate card integration. The owner has authorized voice-controlled
production, playable clips, routed sounds, unified chat and actual multistreaming
as core requirements. The complete hands-free/game-focus acceptance test is not
passed by this checkpoint.

## Capability audit

| Capability | State and actual evidence |
| --- | --- |
| Operator motion | Integrated supplied Motion Pack v1 runtime, independent four-mode preference, OS reduction and confirmed OBS streaming limiter. Browser regressions use controlled service-state inputs; no game-load measurement. |
| Sarge advice | Existing read-only local/optional HTTP advisor. Configuration is labeled configured, not connected. Replies never execute actions. |
| Speech / wake phrase / background PTT | Unavailable. Voice Mod processes audio but does not recognize commands. No new capture graph was installed. |
| Shared actions | Initial host dispatcher implements `clip.save` and `program.take`, behind existing operator endpoints. Other scene, sound and preset actions still need adapters. |
| Manual clips | HTTP save/download and full decoding verified with synthetic frames. Uses existing silent, 5fps, up-to-1280px Program-camera buffer, normally 20 seconds. Not full game/graphics/mixed-audio capture. |
| Sound | Existing local playback and browser-output lease/deduplication. Private voice confirmations and end-to-end output receipt remain unverified. |
| Multichat | No ingestion adapters, normalized history or chat dock. Existing platform monitors do not supply chat. |
| Destinations | Twitch, YouTube, Kick and Rumble have read-only, route-correlated monitors. Facebook/X have partial evidence. TikTok/Instagram remain capability guidance. No new account authorization or live receipt checks performed. |
| Multistream | Existing OBS controls one configured stream service. Independent multi-output publishing/custom destination management are not implemented. |

## Action and clip contract

The host-only registry is allowlisted, has two concurrent slots, retains at most
128 request records for 120 seconds, and rejects unknown actions, invalid parameters,
stale requests and untrusted origins. Practice validates without invoking an adapter.
No generic execute endpoint, shell bridge, advisor-to-action bridge or chat authority
has been added. Manual buttons keep their established API routes. GET
`/api/production/actions` describes the narrow current capability set.

Existing replay-mark and switcher-take bodies optionally accept `request_id` and
`expires_at`. An identified request must include an expiry no more than 120 seconds
in the future. Repeating the exact action/parameters/origin/expiry observes its original
result; changing any of them conflicts. Expired requests never start again. Records
are process-local, so this is not durable exactly-once execution across restarts.
A timed-out adapter is reported as still executing, not succeeded or failed; its
worker is retained rather than repeated. No unbounded work queue is created.

Replay marks accept 2-120 requested seconds and an optional `ending_at` timestamp.
The service copies references from the existing buffer, checks disk headroom, writes
frames, encodes and decodes the entire MP4, then publishes the highlight in its atomic
index. Failures do not publish a highlight or remove previous clips. Responses report
requested and actual length, limited history and zero audio tracks. The UI retains
request identity on uncertain transport/pending outcomes and only announces a playable
save after `video_available` is true.

No credentials or new persisted configuration are introduced by this foundation.
Motion uses one isolated `producerplease.operator.motion.v1` preference; its storage
failure is shown truthfully. It is loaded only in the operator document and excludes
media, artwork, protected branches and their ancestors. Preview/lab actions are absent.

## Validation and next stages

Final canonical gate: **2,472 Python and 218 JavaScript tests passed**. The managed
local app was restarted after confirming the show and recording were inactive and
OBS was closed. Its served action manifest reports the two registered actions and
voice control as unavailable. Post-restart Edge checks passed all five skins at
1080p and Ignite/Daylight at 4K, 1366px and 720px, with zero media starts and all
API mutations blocked. Evidence: `.tmp/refinish/motion/qa-results.json` and
`.tmp/refinish/motion-functional-final-gate.log`.

`tools/qa_manual_clip_http.py` invokes the actual application routes with an isolated
synthetic buffer, without entering application lifespan or opening devices. It verifies
save/download, decode, one save for a duplicate, 422 invalid length and 409 conflicting
request. Output stays in `.tmp/refinish/functional-clip-http/`. The first checked sample
contains 40 decoded frames / 8 seconds at 5fps, no audio. This is an HTTP/encoding test,
not a microphone, game capture, OBS receipt or background-game acceptance test.

`tools/qa_operator_motion.cjs` runs actual Edge UI checks with API mutations and media
starts blocked. It covers the five skins, four motion choices, keyboard, disabled and
dynamic buttons, stable hit bounds, persistence failure, service-state feedback,
streaming reduction, reduced motion, media identity and viewport bounds. It also
inspects the supplied lab only as a local reference.

Next: complete the action adapters and pending-command cancellation, then choose a
host speech/capture integration that reuses physical input ownership and operates
without browser focus. Full Program/audio replay, private acknowledgments and route
receipt precede background game testing. Real authorized chat connectors and two
independent nonpublic output destinations are separate subsequent checkpoints.
Recheck official APIs/scopes/policies before connector implementation; account setup,
public broadcasts, posts, tunnels and paid relays are not authorized by an animation.

Known pre-existing gaps: saved scene takes lack the switcher camera-readiness guard;
scene UI can overstate partial OBS/Spotify outcomes; Stop rundown does not invalidate
an awaited cue. Fix these before allowing Sarge to execute those actions.

Rollback: revert the functional and motion checkpoints normally; preserve runtime
clips, local settings, credentials and the owner's existing AGENTS.md changes. The
old replay API remains compatible with requests that omit new fields.

## Usage authorization

Original shared baseline remains 0%, reset timestamp 1789435596. The owner authorized
a total ceiling of 30% after the 20% pause. Do not establish a new baseline. Shared
metering was 21% at resumption and 25% before activation; check again between
bounded steps.
