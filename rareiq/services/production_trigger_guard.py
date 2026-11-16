"""Pure trigger filtering for a future trusted gesture/head-direction detector.

This does not detect gestures, estimate gaze, acquire a camera, calibrate a model,
or execute production actions. A future adapter must supply observations and own
permission checks, real calibration and dispatch of accepted labels.
"""
from __future__ import annotations

import math
import time


class ProductionTriggerGuard:
    LABELS = frozenset({"open_palm", "closed_fist", "thumbs_up",
                        "look_camera_1", "look_camera_2", "look_camera_3", "look_camera_4"})

    def __init__(self, labels, *, dwell_seconds=.8, cooldown_seconds=2,
                 confidence=.9, neutral_required=True, clock=time.monotonic):
        labels = frozenset(labels)
        if not labels or not labels <= self.LABELS:
            raise ValueError("invalid_trigger_labels")
        if not .4 <= dwell_seconds <= 5 or not 1 <= cooldown_seconds <= 30 or not .8 <= confidence <= 1:
            raise ValueError("invalid_trigger_guard")
        self.labels, self.dwell, self.cooldown, self.confidence = labels, dwell_seconds, cooldown_seconds, confidence
        self.neutral_required, self.clock = bool(neutral_required), clock
        self.armed = False
        self._candidate, self._since, self._last_sample = None, 0, None
        self._latched, self._last_label, self._blocked_until = False, None, 0
        self.practice = True

    def arm(self, *, calibrated=False, practice=True):
        self.stop()
        if any(label.startswith("look_") for label in self.labels) and calibrated is not True:
            return {"ok": False, "reason": "calibration_required"}
        self.practice, self.armed = bool(practice), True
        return {"ok": True, "state": "armed", "practice": self.practice}

    def stop(self):
        self.armed = False
        self._candidate, self._last_sample, self._last_label = None, None, None
        self._latched, self._blocked_until = False, 0

    def manual_override(self):
        """Manual input wins; require a new deliberate arm after any override."""
        self.stop()

    def observe(self, label, confidence, *, tracking=True):
        now = self.clock()
        if not self.armed:
            return {"ok": False, "reason": "trigger_not_armed"}
        if tracking is not True:
            self.stop()
            return {"ok": False, "reason": "tracking_lost"}
        if (not isinstance(confidence, (int, float)) or isinstance(confidence, bool)
                or not math.isfinite(confidence) or confidence < self.confidence or confidence > 1):
            self._candidate, self._last_sample = None, now
            return {"ok": False, "reason": "tracking_not_confident"}
        gap = self._last_sample is None or not 0 <= now - self._last_sample <= .35
        self._last_sample = now
        if label == "neutral":
            self._candidate, self._latched, self._last_label = None, False, None
            return {"ok": True, "state": "neutral"}
        if label not in self.labels:
            self._candidate = None
            return {"ok": False, "reason": "trigger_unassigned"}
        if now < self._blocked_until or (self._latched and (self.neutral_required or label == self._last_label)):
            self._candidate = None
            return {"ok": False, "reason": "trigger_cooldown_or_release_required"}
        if gap or label != self._candidate:
            self._candidate, self._since = label, now
        if now - self._since < self.dwell:
            return {"ok": True, "state": "candidate", "label": label}
        self._blocked_until, self._latched, self._last_label = now + self.cooldown, True, label
        self._candidate = None
        return {"ok": True, "state": "accepted", "label": label, "practice": self.practice, "executed": False}
