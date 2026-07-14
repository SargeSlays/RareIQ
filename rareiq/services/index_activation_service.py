from __future__ import annotations

import threading
import time
from typing import Any


class IndexActivationService:
    def __init__(
        self,
        catalog_engine: Any,
        visual_index: Any,
        recognition: Any,
    ) -> None:
        self.catalog_engine = catalog_engine
        self.visual_index = visual_index
        self.recognition = recognition
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._lock = threading.RLock()
        self._status = {
            "busy": False,
            "phase": "IDLE",
            "started_at": None,
            "elapsed_seconds": 0.0,
            "last_error": None,
            "last_result": None,
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            result = dict(self._status)
        result["visual_index"] = self.visual_index.status()
        return result

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._worker and self._worker.is_alive():
                return {"ok": False, "error": "Index activation is already running."}
            self._status.update({
                "busy": True,
                "phase": "CATALOG",
                "started_at": time.time(),
                "elapsed_seconds": 0.0,
                "last_error": None,
                "last_result": None,
            })

        self._stop.clear()
        self._worker = threading.Thread(
            target=self._run,
            daemon=True,
            name="rareiq-index-activation",
        )
        self._worker.start()
        return {"ok": True, "activation": self.status()}

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        with self._lock:
            if self._status["busy"]:
                self._status["phase"] = "STOPPING"
        return {"ok": True}

    def shutdown(self) -> None:
        self._stop.set()
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=3.0)

    def _run(self) -> None:
        started = time.perf_counter()
        try:
            self.catalog_engine.rebuild_master_index()
            if self._stop.is_set():
                self._finish("PAUSED", {"stopped": True})
                return

            with self._lock:
                self._status["phase"] = "VISUAL_INDEX"

            result = self.visual_index.rebuild(
                progress_callback=self._progress,
                stop_event=self._stop,
            )
            self.recognition.set_global_visual_index(self.visual_index)

            phase = "PAUSED" if result.get("stopped") else "READY"
            self._finish(phase, result)
        except Exception as exc:
            with self._lock:
                self._status.update({
                    "busy": False,
                    "phase": "FAILED",
                    "last_error": str(exc),
                    "elapsed_seconds": round(
                        time.perf_counter() - started, 1
                    ),
                })

    def _progress(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._status["elapsed_seconds"] = round(
                time.time() - float(self._status["started_at"] or time.time()),
                1,
            )

    def _finish(self, phase: str, result: dict[str, Any]) -> None:
        with self._lock:
            self._status.update({
                "busy": False,
                "phase": phase,
                "last_result": result,
                "elapsed_seconds": round(
                    time.time() - float(self._status["started_at"] or time.time()),
                    1,
                ),
            })
