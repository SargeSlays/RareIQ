# Camera reassignment reliability - September 17, 2026

## Cause and correction

The live server traceback located the HTTP 500 in CameraSourceSession.stop:
capture.release raised an OpenCV C++ exception. Stop released the capture from
the request thread before joining the worker, allowing release to overlap read.

The capture worker now owns release in its finally block. Lifecycle operations
are serialized; stop waits up to two seconds without releasing the driver's
handle from another thread. A late read cannot republish a frame after stop.
The manager retains a session whose worker or cleanup is still pending, blocking
replacement capture ownership. Assignment/reconnect/restart report a sanitized
503 when cleanup is incomplete. A slow worker can be retried after it exits.
A driver that actually fails release remains blocked rather than being reopened;
that exceptional condition may require a controlled application restart.

## Evidence

- Seven new isolated regression cases use fake captures and real lifecycle code:
  read/release ordering, worker-owned cleanup, delayed shutdown/retry, release
  failure ownership, manager retention, and three API error responses.
- Focused camera/output tests: 57 passed.
- Canonical release gate: 2,612 Python tests and 275 JavaScript tests passed.
- After a guarded managed restart, actual Insta360 slot 1 passed two consecutive
  unassign/restore cycles and a reconnect through the running HTTP endpoints.
  Fresh frames resumed (final observed age approximately 7 ms).
- OBS Program Browser settings and Program scene visibility were identical
  before and after the live test. Program stayed on slot 1. OBS streaming and
  recording were off throughout; no output was started.

Local evidence: .tmp/camera-reassignment-release-check.log and
.tmp/camera-reassignment-live-check.json. These remain untracked.

This verifies the isolated failure guards and the current physical camera's
reassignment/reconnect path. It does not establish reliability for every driver,
hardware unplug, indefinite native-driver hang, or platform broadcast.

The checkpoint excludes unrelated pre-existing workspace changes and local
settings. Reverting it must preserve OBS configuration, source assignments,
private captures, credentials and unrelated work.
