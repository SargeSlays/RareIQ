"""Experimental local host vision control; observations are not identity proof.

Existing JPEG frames only. Calibration, nonces and observations stay in memory.
The production adapter must check action_authorized INSIDE its final take lock.
"""
from collections import deque
from copy import deepcopy
import hashlib
import math
import secrets
import statistics
import threading
import time
import uuid

from .production_trigger_guard import ProductionTriggerGuard


class VisionTriggerGuard(ProductionTriggerGuard):
    LABELS = ProductionTriggerGuard.LABELS | {"victory"}


HAND_LABELS = frozenset({"open_palm", "thumbs_up", "victory"})
HEAD_LABELS = frozenset(f"look_camera_{n}" for n in range(1, 5))
OBSERVATION_KEYS = {"frame_id", "hand_count", "gesture", "gesture_score", "face_count", "yaw", "pitch"}


def finite(value, low, high):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value) and low <= value <= high


class ProductionVisionController:
    def __init__(self, production_actions, action_validator, camera_ready, frame_provider, assets,
                 *, enabled=False, clock=time.monotonic, wallclock=time.time):
        self.actions, self.validate_action = production_actions, action_validator
        self.camera_ready, self.frame_provider, self.assets = camera_ready, frame_provider, assets
        self.enabled, self.clock, self.wallclock = bool(enabled), clock, wallclock
        self._lock = threading.RLock()
        self._session = None
        self._last_reason = "vision_stopped"

    def _ready(self, slot):
        try:
            result = self.camera_ready(slot)
            return result is True or isinstance(result, dict) and result.get("ready") is True
        except Exception:
            return False

    def _end(self, reason):
        if self._session:
            self._session["guard"].stop()
        self._session = None
        self._last_reason = reason

    def _get(self, nonce):
        session = self._session
        if not session or not isinstance(nonce, str) or not secrets.compare_digest(session["nonce"], nonce):
            raise ValueError("vision_session_expired")
        now = self.clock()
        if now > session["expires"] or now - session["last_contact"] > 3:
            self._end("vision_tracking_lost")
            raise ValueError("vision_tracking_lost")
        if not self._ready(session["camera"]):
            self._end("vision_camera_unavailable")
            raise ValueError("vision_camera_unavailable")
        return session

    def status(self):
        with self._lock:
            if self._session:
                try:
                    self._get(self._session["nonce"])
                except ValueError:
                    pass
            s = self._session
            return {"ok": True, "experimental": True, "enabled": self.enabled,
                    "assets_ready": self.assets.ready(), "active": bool(s),
                    "practice": s["guard"].practice if s else True,
                    "mode": s["mode"] if s else None, "tracking_camera": s["camera"] if s else None,
                    "reason": self._last_reason, "calibrated": sorted(s["calibration"]) if s else [],
                    "camera_ready": {str(n): self._ready(n) for n in range(1, 5)}}

    def start(self, *, mode, tracking_camera, bindings):
        if not self.enabled or not self.assets.ready():
            raise ValueError("vision_assets_unavailable")
        labels = HAND_LABELS if mode == "hands" else HEAD_LABELS if mode == "head" else frozenset()
        if type(tracking_camera) is not int or tracking_camera not in range(1, 5) or not self._ready(tracking_camera):
            raise ValueError("vision_camera_unavailable")
        if not isinstance(bindings, dict) or not bindings or not set(bindings) <= labels:
            raise ValueError("vision_invalid_bindings")
        normalized = {}
        for label, action in bindings.items():
            if not isinstance(action, dict) or set(action) != {"action_id", "params"} or action["action_id"] not in {"program.take", "scene.take"}:
                raise ValueError("vision_invalid_action")
            params = action["params"]
            if not isinstance(params, dict):
                raise ValueError("vision_invalid_action")
            if action["action_id"] == "program.take":
                if (not set(params) <= {"preview_slot", "transition", "duration_ms"}
                        or type(params.get("preview_slot")) is not int or params["preview_slot"] not in range(1, 5)
                        or params.get("transition", "fade") not in {"cut", "fade"}):
                    raise ValueError("vision_invalid_action")
            elif set(params) != {"scene_id"}:
                raise ValueError("vision_invalid_action")
            normalized[label] = {"action_id": action["action_id"], "params": self.validate_action(action["action_id"], action["params"])}
        if mode == "head" and len(bindings) < 2:
            raise ValueError("vision_two_directions_required")
        with self._lock:
            self._end("vision_practice")
            now = self.clock()
            guard = VisionTriggerGuard(normalized, clock=self.clock, neutral_required=mode == "hands")
            if mode == "hands":
                guard.arm(practice=True)
            self._session = {"nonce": secrets.token_urlsafe(32), "camera": tracking_camera, "mode": mode,
                             "bindings": normalized, "guard": guard, "expires": now + 600, "last_contact": now,
                             "last_observation": None, "last_hash": None, "frame": None,
                             "calibration": {}, "samples": deque(maxlen=16), "pending": {}}
            return {"ok": True, "nonce": self._session["nonce"], "practice": True, "expires_in": 600}

    def stop(self, nonce):
        with self._lock:
            # A delayed old browser's stop must not stop a newer practice session.
            if self._session and secrets.compare_digest(self._session["nonce"], str(nonce)):
                self._end("vision_stopped")
            return {"ok": True, "state": "stopped"}

    def manual_override(self):
        with self._lock:
            self._end("vision_manual_override")

    def frame(self, nonce, slot):
        with self._lock:
            s = self._get(nonce)
            if slot != s["camera"]:
                raise ValueError("vision_reference_camera_mismatch")
            try:
                data = self.frame_provider(slot)
            except Exception:
                data = None
            if not isinstance(data, bytes) or not 4 <= len(data) <= 8 * 1024 * 1024 or not data.startswith(b"\xff\xd8"):
                self._end("vision_frame_unavailable")
                raise ValueError("vision_frame_unavailable")
            digest = hashlib.sha256(data).digest()
            if s["last_hash"] == digest:
                # Frozen frames can never accumulate dwell time, even if a client retries.
                s["frame"] = None
                s["guard"].observe("neutral", 0)
                raise ValueError("vision_waiting_for_new_frame")
            s["last_hash"] = digest
            s["frame"] = (secrets.token_urlsafe(24), self.clock())
            return data, s["frame"][0]

    def calibrate(self, nonce, target_slot):
        with self._lock:
            s = self._get(nonce)
            label = f"look_camera_{target_slot}"
            if type(target_slot) is not int or s["mode"] != "head" or label not in s["bindings"]:
                raise ValueError("vision_invalid_calibration_target")
            if not s["guard"].practice:
                raise ValueError("vision_return_to_practice")
            now = self.clock()
            points = [p for p in s["samples"] if now - p[0] <= 1.5]
            if len(points) < 5 or points[-1][0] - points[0][0] < .6:
                raise ValueError("vision_hold_direction")
            yaw, pitch = statistics.mean(p[1] for p in points), statistics.mean(p[2] for p in points)
            if any(math.hypot(p[1] - yaw, p[2] - pitch) > 4 for p in points):
                raise ValueError("vision_hold_direction")
            if any(key != label and math.hypot(yaw - p[0], pitch - p[1]) < 15 for key, p in s["calibration"].items()):
                raise ValueError("vision_directions_too_close")
            s["calibration"][label] = (yaw, pitch)
            s["samples"].clear()
            s["guard"].stop()
            if set(s["bindings"]) <= s["calibration"].keys():
                s["guard"].arm(calibrated=True, practice=True)
            return {"ok": True, "calibrated": sorted(s["calibration"]), "ready": s["guard"].armed}

    def arm(self, nonce, practice):
        if type(practice) is not bool:
            raise ValueError("vision_invalid_mode")
        with self._lock:
            s = self._get(nonce)
            if s["last_observation"] is None or self.clock() - s["last_observation"] > .75:
                raise ValueError("vision_fresh_tracking_required")
            calibrated = s["mode"] == "hands" or len(s["calibration"]) >= 2 and set(s["bindings"]) <= s["calibration"].keys()
            result = s["guard"].arm(calibrated=calibrated, practice=practice)
            if not result["ok"]:
                raise ValueError("vision_calibration_required")
            s["pending"].clear()
            self._last_reason = "vision_practice" if practice else "vision_armed"
            return result

    def action_authorized(self, request_id):
        """Call inside the production lock, immediately before the actual take."""
        with self._lock:
            s = self._session
            if not s or request_id not in s["pending"]:
                return False
            try:
                self._get(s["nonce"])
            except ValueError:
                return False
            return (s["guard"].armed and not s["guard"].practice
                    and self.clock() <= s["pending"][request_id]
                    and s["last_observation"] is not None and self.clock() - s["last_observation"] <= .75)

    def observe(self, nonce, observation):
        with self._lock:
            s = self._get(nonce)
            if (not isinstance(observation, dict) or set(observation) != OBSERVATION_KEYS
                    or any(type(observation[k]) is not int or observation[k] not in range(3) for k in ("face_count", "hand_count"))
                    or not isinstance(observation["gesture"], str) or observation["gesture"] not in HAND_LABELS | {"neutral"}
                    or not finite(observation["gesture_score"], 0, 1)):
                s["frame"], s["last_observation"] = None, None
                s["samples"].clear()
                s["pending"].clear()
                s["guard"].observe("neutral", 0)
                raise ValueError("vision_invalid_observation")
            now = self.clock()
            frame = s["frame"]
            s["frame"] = None  # One use even when validation fails.
            if not frame or observation["frame_id"] != frame[0] or not 0 <= now - frame[1] <= 1:
                raise ValueError("vision_stale_frame")
            s["last_contact"] = now
            label, confidence = "neutral", 1
            if s["mode"] == "hands":
                count = observation["hand_count"]
                if count > 1:
                    label, confidence = "neutral", 0
                elif count == 1:
                    label, confidence = observation["gesture"], observation["gesture_score"]
                if count == 0:
                    # Empty frame is release, not a pose. Camera liveness still required.
                    label = "neutral"
            else:
                if observation["face_count"] == 0:
                    self._end("vision_tracking_lost")
                    return {"ok": False, "reason": "vision_tracking_lost", "stopped": True}
                if observation["face_count"] != 1 or not finite(observation["yaw"], -65, 65) or not finite(observation["pitch"], -45, 45):
                    s["samples"].clear()
                    label, confidence = "neutral", 0
                else:
                    yaw, pitch = observation["yaw"], observation["pitch"]
                    s["samples"].append((now, yaw, pitch))
                    distances = sorted((math.hypot(yaw - p[0], pitch - p[1]), key) for key, p in s["calibration"].items())
                    if distances and distances[0][0] <= 8 and (len(distances) == 1 or distances[1][0] - distances[0][0] >= 5):
                        label = distances[0][1]
                    elif distances and distances[0][0] <= 12:
                        confidence = 0
            s["last_observation"] = now if confidence >= .9 else None
            result = s["guard"].observe(label, confidence)
            result.update({"observed": label, "practice": s["guard"].practice, "calibrated": sorted(s["calibration"])})
            if result.get("state") != "accepted":
                return result
            binding = deepcopy(s["bindings"][label])
            if s["guard"].practice:
                return {**result, "state": "practice_match", "action": binding, "executed": False}
            request_id = "vision-" + uuid.uuid4().hex
            s["pending"] = {k: v for k, v in s["pending"].items() if v > now}
            s["pending"][request_id] = now + .75
        outcome = self.actions.dispatch(binding["action_id"], binding["params"], origin="host_gesture",
                                        request_id=request_id, expires_at=self.wallclock() + 5,
                                        cancelled=lambda: not self.action_authorized(request_id))
        return {**result, "state": "action_result", "action": binding, "outcome": outcome}
