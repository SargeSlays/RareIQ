from __future__ import annotations

import json
import math
import re
import shutil
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Callable

from rareiq.services.media_storage import atomic_json


class InstantReplayService:
    MAX_HIGHLIGHTS = 25

    def __init__(self, root: Path, frame_provider: Callable[[int], bytes | None], program_slot_provider: Callable[[], int], *, fps: int = 5, buffer_seconds: int = 20, frame_context_provider: Callable[[int], dict[str, Any]] | None = None) -> None:
        if not 1 <= fps <= 60 or not 2 <= buffer_seconds <= 120:
            raise ValueError("invalid_replay_buffer_limits")
        self.root, self.frame_provider, self.program_slot_provider = root, frame_provider, program_slot_provider
        self.fps, self.buffer_seconds = fps, buffer_seconds
        self.frame_context_provider = frame_context_provider
        self._buffer_source: tuple | None = None
        self._frames: deque[tuple[float, int, bytes]] = deque(maxlen=fps * buffer_seconds)
        self._lock, self._stop = threading.RLock(), threading.Event()
        self._thread: threading.Thread | None = None
        self._last_error = ""
        self._buffer_epoch = 0
        self._highlights: list[dict[str, Any]] = []
        self._playback = {"active": False, "highlight_id": None, "generation": 0, "speed": 1.0, "started_at": 0.0}
        self._load()

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._frames.clear()
            self._buffer_epoch += 1
            self._stop.clear()
            self._thread = threading.Thread(target=self._capture_loop, name="rareiq-instant-replay", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread: self._thread.join(timeout=1.5)
        with self._lock:
            self._frames.clear()
            self._buffer_epoch += 1
            self.stop_playback()

    def _capture_loop(self) -> None:
        interval = 1 / self.fps
        while not self._stop.wait(interval):
            self._capture_once()

    def _capture_once(self) -> None:
        try:
            slot = int(self.program_slot_provider())
            source = self._frame_source(slot)
            frame = self.frame_provider(slot)
            if self.frame_context_provider and self._frame_source(slot) != source:
                raise ValueError("replay_source_changed_during_capture")
            if not isinstance(frame, bytes) or not frame:
                raise ValueError("frame_unavailable")
        except Exception:
            # A provider/device failure must not silently kill the rolling buffer.
            with self._lock:
                self._frames.clear()
                self._buffer_epoch += 1
                self._last_error = "Program camera frames are unavailable."
            return
        with self._lock:
            if not self._stop.is_set():
                self._prune_frames()
                if self._buffer_source is not None and self._buffer_source != source:
                    self._buffer_epoch += 1
                self._buffer_source = source
                self._frames.append((time.time(), slot, frame))
                self._last_error = ""

    def _frame_source(self, slot: int) -> tuple:
        if self.frame_context_provider is None:
            return (slot,)
        context = self.frame_context_provider(slot)
        age = float(context.get("frame_age_seconds", math.inf))
        if context.get("connected") is not True or not context.get("source_id") or not math.isfinite(age) or not 0 <= age <= 1:
            raise ValueError("replay_frame_not_fresh")
        return (slot, context["source_id"], context.get("stream_session_id"))

    def _prune_frames(self) -> None:
        cutoff = time.time() - self.buffer_seconds
        while self._frames and self._frames[0][0] < cutoff:
            self._frames.popleft()

    def mark(self, seconds: int = 8, name: str = "Highlight") -> dict[str, Any]:
        try:
            cutoff = time.time() - max(2, min(self.buffer_seconds, int(seconds)))
        except (ValueError, TypeError, OverflowError):
            return {"created": False, "reason": "invalid_replay_length"}
        with self._lock:
            self._prune_frames()
            frames = [item for item in self._frames if item[0] >= cutoff]
        return self.save_frames(frames, name)

    def buffer_window(self, start: float, end: float) -> dict[str, Any]:
        """Copy frame references, never open another camera or duplicate JPEG data."""
        with self._lock:
            self._prune_frames()
            return {"epoch": self._buffer_epoch, "frames": [item for item in self._frames if start <= item[0] <= end]}

    def save_frames(self, frames: list[tuple[float, int, bytes]], name: str, *, auto_clip: dict[str, Any] | None = None, cancelled: Callable[[], bool] = lambda: False) -> dict[str, Any]:
        """Manual and automatic highlights share one atomic store and retention limit."""
        if not frames: return {"created": False, "reason": "replay_buffer_empty"}
        highlight_id = uuid.uuid4().hex[:12]
        path = self.root / highlight_id
        item = {"id": highlight_id, "name": str(name or "Highlight")[:60], "frames": len(frames), "fps": self.fps, "duration_seconds": round(len(frames) / self.fps, 1), "slot_id": frames[-1][1], "created_at": time.time(), "path": str(path)}
        created_directory = False
        try:
            path.mkdir(parents=True, exist_ok=False)
            created_directory = True
            for index, (_, _, data) in enumerate(frames):
                if cancelled():
                    raise InterruptedError("auto_clip_cancelled")
                if (path / f"{index:04d}.jpg").write_bytes(data) != len(data):
                    raise OSError("incomplete_replay_frame_write")
            if auto_clip is not None:
                self._encode_video(path, len(frames), cancelled)
                item.update(auto_clip=dict(auto_clip), video_available=True)
            with self._lock:
                if cancelled():
                    raise InterruptedError("auto_clip_cancelled")
                self._expire_playback()
                previous = self._highlights
                retained = [item, *previous]
                active_id = self._playback["highlight_id"] if self._playback["active"] else None
                retired = []
                while len(retained) > self.MAX_HIGHLIGHTS:
                    index = next(index for index in range(len(retained) - 1, -1, -1) if retained[index]["id"] != active_id)
                    retired.append(retained.pop(index))
                self._highlights = retained
                try:
                    self._persist()
                except OSError:
                    self._highlights = previous
                    raise
                for retired_item in retired:
                    self._remove_highlight_files(retired_item)
        except Exception as exc:
            if created_directory:
                self._remove_highlight_files(item)
            reason = "auto_clip_cancelled" if isinstance(exc, InterruptedError) else "replay_storage_unavailable" if isinstance(exc, OSError) else "clip_encoding_failed"
            return {"created": False, "reason": reason}
        return {"created": True, "highlight": self._public(item)}

    def _encode_video(self, path: Path, frame_count: int, cancelled: Callable[[], bool]) -> None:
        """Silent 5fps (buffer cadence) MP4, bounded to 1280px; preserve the full frame."""
        import cv2
        import numpy as np

        writer = None
        try:
            first = cv2.imread(str(path / "0000.jpg"))
            if first is None:
                raise ValueError("invalid_clip_frame")
            height, width = first.shape[:2]
            scale = min(1.0, 1280 / max(height, width))
            size = (max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2))
            writer = cv2.VideoWriter(str(path / "clip.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), self.fps, size)
            if not writer.isOpened():
                raise ValueError("clip_encoder_unavailable")
            for index in range(frame_count):
                if cancelled():
                    raise InterruptedError("auto_clip_cancelled")
                frame = cv2.imread(str(path / f"{index:04d}.jpg"))
                if frame is None:
                    raise ValueError("invalid_clip_frame")
                h, w = frame.shape[:2]
                ratio = min(size[0] / w, size[1] / h)
                resized = cv2.resize(frame, (max(1, int(w * ratio)), max(1, int(h * ratio))))
                canvas = np.zeros((size[1], size[0], 3), dtype=np.uint8)
                rh, rw = resized.shape[:2]
                x, y = (size[0] - rw) // 2, (size[1] - rh) // 2
                canvas[y:y + rh, x:x + rw] = resized
                writer.write(canvas)
            writer.release()
            writer = None
            # File existence alone is not evidence that the encoder produced a clip.
            video = cv2.VideoCapture(str(path / "clip.mp4"))
            try:
                decoded = 0
                while decoded <= frame_count and video.read()[0]:
                    decoded += 1
                if decoded != frame_count:
                    raise ValueError("incomplete_clip_video")
            finally:
                video.release()
        except cv2.error as exc:
            raise ValueError("clip_encoding_failed") from exc
        finally:
            if writer is not None:
                writer.release()

    def video(self, highlight_id: str) -> Path | None:
        with self._lock:
            item = next((value for value in self._highlights if value["id"] == highlight_id), None)
            root = self._safe_highlight_root(item) if item else None
            if not root or not item.get("video_available"):
                return None
            try:
                path = (root / "clip.mp4").resolve()
                return path if path.parent == root and path.is_file() and path.stat().st_size else None
            except OSError:
                return None

    def take(self, highlight_id: str, speed: float = 1.0) -> dict[str, Any]:
        try:
            speed = float(speed)
            if not math.isfinite(speed) or not .25 <= speed <= 2.0:
                raise ValueError("invalid_replay_speed")
        except (ValueError, TypeError):
            return {"updated": False, "reason": "invalid_replay_speed"}
        with self._lock:
            item = next((value for value in self._highlights if value["id"] == highlight_id), None)
            if not item: return {"updated": False, "reason": "highlight_not_found"}
            if any(self.frame(highlight_id, index) is None for index in range(item["frames"])):
                return {"updated": False, "reason": "highlight_frames_unavailable"}
            self._playback = {"active": True, "highlight_id": highlight_id, "generation": int(self._playback["generation"]) + 1, "speed": speed, "started_at": time.time()}
            return {"updated": True, **self.snapshot()}

    def stop_playback(self) -> dict[str, Any]:
        with self._lock: self._playback.update({"active": False, "highlight_id": None, "generation": int(self._playback["generation"]) + 1}); return self.snapshot()

    def frame(self, highlight_id: str, index: int) -> Path | None:
        with self._lock: item = next((value for value in self._highlights if value.get("id") == highlight_id), None)
        if not item or not 0 <= index < item["frames"]: return None
        highlight_root = self._safe_highlight_root(item)
        if highlight_root is None:
            return None
        try:
            path = (highlight_root / f"{index:04d}.jpg").resolve()
            return path if path.parent == highlight_root and path.is_file() and path.stat().st_size > 0 else None
        except OSError:
            return None

    @staticmethod
    def _public(item: dict[str, Any]) -> dict[str, Any]: return {key: value for key, value in item.items() if key != "path"}

    def _expire_playback(self) -> None:
        if not self._playback["active"]:
            return
        item = next((item for item in self._highlights if item["id"] == self._playback["highlight_id"]), None)
        if item is None or time.time() - self._playback["started_at"] >= item["frames"] / item["fps"] / self._playback["speed"]:
            self._playback.update(active=False, highlight_id=None, generation=int(self._playback["generation"]) + 1)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._prune_frames()
            self._expire_playback()
            return {"buffer_seconds": self.buffer_seconds, "buffered_frames": len(self._frames), "fps": self.fps, "last_error": self._last_error, "highlights": [self._public(item) for item in self._highlights], "playback": dict(self._playback)}

    def _persist(self) -> None:
        atomic_json(self.root / "highlights.json", self._highlights)

    def _load(self) -> None:
        try:
            payload = json.loads((self.root / "highlights.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return
        if not isinstance(payload, list):
            return
        seen = set()
        for item in payload:
            if not isinstance(item, dict) or self._safe_highlight_root(item) is None:
                continue
            try:
                identifier = str(item.get("id") or "")
                frames, fps = int(item["frames"]), int(item.get("fps", self.fps))
                created_at = float(item.get("created_at", 0))
                if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identifier) or identifier in seen or not 1 <= fps <= 60 or not 1 <= frames <= fps * 120 or not math.isfinite(created_at):
                    continue
                clean = {"id": identifier, "name": str(item.get("name") or "Highlight")[:60], "frames": frames, "fps": fps, "duration_seconds": round(frames / fps, 1), "slot_id": int(item.get("slot_id", 1)), "created_at": created_at, "path": str(item["path"])}
                if isinstance(item.get("auto_clip"), dict):
                    clean["auto_clip"] = dict(item["auto_clip"])
                    clean["video_available"] = item.get("video_available") is True
            except (KeyError, ValueError, TypeError, OverflowError):
                continue
            self._highlights.append(clean)
            seen.add(identifier)
            if len(self._highlights) >= self.MAX_HIGHLIGHTS:
                break

    def _safe_highlight_root(self, item: dict[str, Any]) -> Path | None:
        try:
            root = self.root.resolve()
            candidate = Path(str(item.get("path") or "")).resolve()
            candidate.relative_to(root)
        except (OSError, ValueError):
            return None
        return candidate if candidate != root and candidate.is_dir() else None

    def _remove_highlight_files(self, item: dict[str, Any]) -> None:
        path = self._safe_highlight_root(item)
        if path is not None:
            shutil.rmtree(path, ignore_errors=True)
