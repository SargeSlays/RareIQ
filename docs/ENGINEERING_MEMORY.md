# RareIQ engineering memory

This file turns regressions into permanent operating knowledge. It is not a bug
backlog. Add an entry when a defect repeats, escapes visual review, or exposes a
class of failure that can be prevented automatically.

## The rule

Every qualifying regression records:

1. visible symptom and affected workflow;
2. root cause rather than only the edited selector/function;
3. smallest durable guard: unit/contract/browser test, release check, or explicit
   operator preflight;
4. environments verified (dark/light, 1080p/4K/narrow, hardware/offline service);
5. any limitation that still needs real-device or live-platform testing.

Do not keep duplicate production implementations “just in case.” Git preserves
deleted and replaced code. Keep the current tree understandable and use commits,
tags, and archives to recover older behavior.

## Learned patterns

### Cascade and legacy-style regressions

- Symptom: old colors, spacing, or card-only controls return after a new shell is
  added.
- Root cause: late or more-specific legacy selectors override the new semantic
  layer; visual inspection covered only one workspace or resolution.
- Permanent guard: keep the final shell stylesheet last, assert the asset order,
  test header controls per workspace, and inspect dark/light plus 1080p/4K/narrow.

### Async readiness and race regressions

- Symptom: stale results authorize a button, a second click starts twice, or a
  slow OBS probe makes a fresh camera appear stale.
- Root cause: state was sampled before a slow await or responses were accepted
  after the selected workflow changed.
- Permanent guard: generation tokens, server-side locks, current-workflow checks,
  no retries for mutating operations, and concurrency/stale-response tests.

### Test-pass versus running-runtime regressions

- Symptom: source code is fixed but the open browser still serves old behavior.
- Root cause: the server or cached static asset was not restarted/version-busted.
- Permanent guard: cache-bust changed assets, restart only after checking that no
  show/recording/stream is active, and verify the live API/UI after restart.

### Hardware ownership and external integrations

- Symptom: OBS cannot use a camera already owned by RareIQ, or an offline external
  service is mistaken for a working broadcast.
- Root cause: physical-device ownership and external encoder/platform receipt are
  different readiness layers.
- Permanent guard: RareIQ browser outputs for owned cameras/audio, explicit local
  versus destination readiness, and no claim of live verification without actual
  destination receipt.

### Credentials and local evidence

- Symptom: OBS passwords or diagnostic camera frames appear as untracked source.
- Root cause: machine-local files were created before ignore and release rules.
- Permanent guard: ignore `obs_settings.json` and `.tmp/`, preserve them locally,
  and make the release gate reject tracked local configuration/private keys.

## Checkpoint procedure

Before a checkpoint or push:

1. confirm the active show, recording, and OBS stream are off before restarts;
2. review untracked files, deletions, and large files, then stage the intended
   checkpoint so staged whitespace is visible to the gate;
3. run `python -B tools/release_check.py --require-node` in the pinned environment;
4. scan staged paths for credentials and generated runtime state;
5. commit a coherent checkpoint with tests/docs, push it, then verify the remote
   commit ID;
6. create and verify a dated source archive outside the repository when the phase
   is large or risky.

The code guardian should report findings and add guards; it must not silently
rewrite user work, remove evidence, expose credentials, or claim untested live
integrations are working.
