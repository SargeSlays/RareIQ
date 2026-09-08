# Local voice command checkpoint

September 8, 2026. This continues the existing Producer, Please studio and Sarge
action foundation. It does not replace the read-only Sarge advisor or install a
second microphone, assistant model or broadcaster.

## Operator workflow

1. Open Voice studio, standalone or docked, and start the existing Voice Mod input.
2. Leave **Practice** checked. Choose Wake phrases or Hold Ctrl+Alt+V, then select
   **Start listening** in the Sarge console at the top of Voice studio.
3. In Wake mode, say “Producer please” or “Sarge”, followed by “camera one” through “camera four”,
   “clip that”, or “save the last fifteen/thirty/sixty/one hundred twenty seconds”.
   In Hold mode, hold Ctrl+Alt+V through the whole command; the prefix is optional.
4. Practice recognizes and validates without executing. Stop listening before
   unchecking Practice and explicitly starting again to enable these two actions.
5. **Stop listening** releases only the speech branch. Ctrl+Alt+Backspace on the
   Windows host stops voice commands without stopping the show. Changing/stopping
   Voice Mod, losing the device or closing the page also stops speech ownership.

Pause after each command. This checkpoint accepts one utterance at a time, keeps
no backlog and never retries an uncertain command with a new identity. The existing
clip tray supplies Download MP4. Current clips contain the silent Program-camera
buffer, normally 20 seconds at 5fps, not full game composition or mixed audio.
Short history is disclosed after saving.

Only the local studio can arm or supply audio. English (US) Windows speech support
must be installed. An inactive Voice Mod input keeps Start listening disabled.
Arming is never persisted or automatic. Feedback is operator text only.

**Limits:** Native hold-to-talk is implemented, but physical/game-keypress acceptance
and private spoken confirmations remain outstanding.
The selected Voice Mod microphone may also reach Program: these commands are not
automatically private. A wake phrase is not speaker authentication. Background
operation depends on the browser/input graph staying active; browser closure,
suspension, revoked permission and physical mute cannot be bypassed. No injection
into games or anti-cheat changes are used. Real microphone accuracy, noisy/guest
speech, game-focus reliability, headphone routing and game-load impact remain
unverified. Stop cannot revoke a production adapter that has already begun.

## Implementation and boundaries

An AudioWorklet borrows the existing raw source before Voice Mod effects and program
gain. It uses a silence-only output through a zero-gain node in that same context,
so speech adds no monitor audio or physical input owner. Voice activity segmentation
is bounded to six seconds; the browser sends mono 16kHz PCM16 WAV with an audio-clock
timestamp. The host rejects oversized/malformed/stale audio, overlapping jobs,
conflicting sequences, missing ownership and confidence below 0.8.

The installed Windows System.Speech en-US engine processes memory audio through a
constant hidden helper. No cloud call, model download, GPU allocation or raw-audio
log is introduced. CPU processing is appropriate for this installed engine.
The grammar is finite; arbitrary transcripts and advisor/chat replies cannot become
production actions. `program.take` and `clip.save` use the same registry as manual
controls. Original timestamps anchor clips; accepted request IDs prevent duplicate
saves. Timed-out actions retain their Future and are observed without re-execution.

An owned heartbeat expires abandoned sessions after 30 seconds. One fixed native
key observer checks only the configured chords while armed. Hold mode registers
Ctrl+Alt+V with Windows and fails closed if unavailable. Both first and last voiced
timestamps must fit one native held interval before recognition; the host keeps at
most eight intervals for 30 seconds. The microphone remains active and can still
be routed to Program: holding the key only gates command acceptance. The key
registration is removed on Stop, errors and shutdown. Observer failure revokes the
listening session, including Wake mode's emergency control. Stop
invalidates pending recognition and suppresses late feedback; an adapter not yet
entered also checks cancellation. Already-entered effects can finish.

Primary API reference: Microsoft's [SpeechRecognitionEngine documentation](https://learn.microsoft.com/en-us/dotnet/api/system.speech.recognition.speechrecognitionengine?view=netframework-4.8.1).

## Evidence and repeatable checks

Sarge console UI follow-up: **2,525 Python and 239 JavaScript tests passed**.
Both command modes passed served Edge checks across Ignite/Daylight at 1080p,
4K, 1366px and 720px, plus a 354px dock. Original node identities survive docking
and return; actual voice writes and media starts were blocked. Evidence:
`.tmp/refinish/sarge-ui-gate.log` and `.tmp/refinish/voice/qa-results-{wake,ptt}.json`.

Hold-to-talk follow-up gate: **2,524 Python and 238 JavaScript tests passed**.
The restarted managed app registered PTT in Practice, rejected supplied synthetic
audio outside a held interval before recognition, and explicitly stopped/released
the shortcut. Post-restart Edge PTT controls passed with inert voice endpoints.
Evidence: `.tmp/refinish/voice-ptt-gate.log` and
`.tmp/refinish/voice/qa-results-ptt.json`. The first wake-command checkpoint is
`9ebb40dc`; this follow-up retains all of its microphone ownership protections.

Final gate: **2,506 Python and 235 JavaScript tests passed**. The managed app was
restarted with show/recording inactive and OBS closed. Its real voice endpoint
recognized the worklet-generated synthetic command in Practice, returned validated
without executing, and was explicitly stopped. Post-restart served Edge QA passed.
Evidence: `.tmp/refinish/voice-final-gate.log`.

- Installed recognizer: Microsoft Speech Recognizer 8.0, en-US. Real recognition of
  18 synthetic phrases matched all 18, confidence 0.9859–0.9919. Per-utterance engine
  measurements were about 0.28–0.38 seconds, excluding capture/game-load conditions.
  Evidence: `.tmp/refinish/windows-speech-proof.json`.
- `tools/qa_voice_command_http.py` uses memory-only synthetic speech and the real
  application routes with an isolated synthetic replay buffer, without application
  lifespan or hardware capture. It saved/downloaded a playable four-second MP4 from
  a 30-second request, decoded all 20 frames, and saved once on duplicate audio.
  The foreground window was unchanged during this synthetic test; this does not
  establish a genuine game session. Outputs: `.tmp/refinish/voice-http/`.
- The optional `RAREIQ_QA_VOICE_WAV` browser check processed memory-synthesized speech
  into a 3.08-second worklet WAV. Supplying that WAV with `--input-wav` to the HTTP
  proof passed real recognition, one clip save, download and full decoding. This
  joins the tested layers without opening a microphone or using a production feed.
- `tools/qa_studio_voice_control.cjs` exercises the served UI and real offline
  AudioWorklet with synthetic input; all actual API writes and media starts are
  blocked. It checks input ownership, Practice, timestamps, WAV format, stopping
  and Ignite/Daylight layouts. Outputs: `.tmp/refinish/voice/`.
- Unit/HTTP regressions cover strict commands, practice, confidence, malformed/stale
  input, duplicates, stop during recognition, busy jobs, emergency/lease shutdown,
  post-error shutdown, late action completion and nonlocal rejection.
- Native-key tests cover shortcut conflicts, one-interval start/end validation,
  bounded history, failed observers and cleanup. Actual Windows registration and
  removal passed with foreground unchanged and no key injection. Bare “camera two”
  passed real synthetic recognition. Physical hold-to-talk during gameplay is not
  established by registration or injected native-API test doubles.

No real microphone, live recording, audience audio or platform delivery is claimed
by these tests. One earlier synthesis diagnostic may have played a test phrase after
an output binding error; corrected tests fail immediately and select null output
before binding memory output. This incident and durable guard are recorded in
engineering memory.

## Recovery and allowance

Revert this checkpoint normally to remove voice arming; retain existing clips,
Voice Mod settings and user-authored AGENTS.md changes. No voice preferences,
credentials, transcript history or user-audio files are persisted.

The owner subsequently approved a total 40% ceiling and prioritized a UI update.
Original shared baseline remains 0%, reset timestamp 1789435596. Usage was 27% at
wake resumption, 32% after PTT activation, 36% at UI resumption and 37% during the
UI checkpoint, reaching 38% during verification. These shared readings include
other account activity. This bounded
stage improves the existing Sarge console; private monitor routing/full Program
audio remain a separate substantial stage. Do not establish a new baseline.
