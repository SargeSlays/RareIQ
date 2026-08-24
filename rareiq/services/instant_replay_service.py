from __future__ import annotations

import json
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Callable


class InstantReplayService:
    def __init__(self, root: Path, frame_provider: Callable[[int], bytes | None], program_slot_provider: Callable[[], int], *, fps: int = 5, buffer_seconds: int = 20) -> None:
        self.root, self.frame_provider, self.program_slot_provider = root, frame_provider, program_slot_provider
        self.fps, self.buffer_seconds = fps, buffer_seconds
        self._frames: deque[tuple[float, int, bytes]] = deque(maxlen=fps * buffer_seconds)
        self._lock, self._stop = threading.RLock(), threading.Event()
        self._thread: threading.Thread | None = None
        self._highlights: list[dict[str, Any]] = []
        self._playback = {"active": False, "highlight_id": None, "generation": 0, "speed": 1.0, "started_at": 0.0}
        self._load()

    def start(self) -> None:
        if self._thread and self._thread.is_alive(): return
        self._stop.clear(); self._thread = threading.Thread(target=self._capture_loop, name="rareiq-instant-replay", daemon=True); self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread: self._thread.join(timeout=1.5)

    def _capture_loop(self) -> None:
        interval = 1 / self.fps
        while not self._stop.wait(interval):
            slot = int(self.program_slot_provider())
            frame = self.frame_provider(slot)
            if frame:
                with self._lock: self._frames.append((time.time(), slot, frame))

    def mark(self, seconds: int = 8, name: str = "Highlight") -> dict[str, Any]:
        cutoff = time.time() - max(2, min(self.buffer_seconds, int(seconds)))
        with self._lock: frames = [item for item in self._frames if item[0] >= cutoff]
        if not frames: return {"created": False, "reason": "replay_buffer_empty"}
        highlight_id, path = uuid.uuid4().hex[:12], self.root / uuid.uuid4().hex[:12]
        path.mkdir(parents=True, exist_ok=True)
        for index, (_, _, data) in enumerate(frames): (path / f"{index:04d}.jpg").write_bytes(data)
        item = {"id": highlight_id, "name": str(name or "Highlight")[:60], "frames": len(frames), "fps": self.fps, "duration_seconds": round(len(frames) / self.fps, 1), "slot_id": frames[-1][1], "created_at": time.time(), "path": str(path)}
        with self._lock: self._highlights.insert(0, item); self._highlights = self._highlights[:25]; self._persist()
        return {"created": True, "highlight": self._public(item)}

    def take(self, highlight_id: str, speed: float = 1.0) -> dict[str, Any]:
        with self._lock:
            item = next((value for value in self._highlights if value["id"] == highlight_id), None)
            if not item: return {"updated": False, "reason": "highlight_not_found"}
            self._playback = {"active": True, "highlight_id": highlight_id, "generation": int(self._playback["generation"]) + 1, "speed": max(.25, min(2.0, float(speed))), "started_at": time.time()}
            return {"updated": True, **self.snapshot()}

    def stop_playback(self) -> dict[str, Any]:
        with self._lock: self._playback.update({"active": False, "highlight_id": None, "generation": int(self._playback["generation"]) + 1}); return self.snapshot()

    def frame(self, highlight_id: str, index: int) -> Path | None:
        with self._lock: item = next((value for value in self._highlights if value["id"] == highlight_id), None)
        if not item: return None
        path = (Path(item["path"]) / f"{max(0, index):04d}.jpg").resolve()
        return path if path.is_file() and Path(item["path"]).resolve() in path.parents else None

    @staticmethod
    def _public(item: dict[str, Any]) -> dict[str, Any]: return {key: value for key, value in item.items() if key != "path"}
    def snapshot(self) -> dict[str, Any]:
        with self._lock: return {"buffer_seconds": self.buffer_seconds, "buffered_frames": len(self._frames), "fps": self.fps, "highlights": [self._public(item) for item in self._highlights], "playback": dict(self._playback)}
    def _persist(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True); (self.root / "highlights.json").write_text(json.dumps(self._highlights, indent=2), encoding="utf-8")
    def _load(self) -> None:
        try: self._highlights = [item for item in json.loads((self.root / "highlights.json").read_text(encoding="utf-8")) if Path(str(item.get("path", ""))).is_dir()][:25]
        except (OSError, ValueError, TypeError): self._highlights = []
