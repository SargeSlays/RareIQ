from __future__ import annotations

import queue
import threading
import time
import uuid
from typing import Any, Callable


class JobQueueService:
    """Single-lane background queue for heavy RareIQ maintenance jobs."""

    def __init__(self) -> None:
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._worker = threading.Thread(
            target=self._run,
            daemon=True,
            name="rareiq-job-queue",
        )
        self._jobs: dict[str, dict[str, Any]] = {}
        self._current_job_id: str | None = None
        self._worker.start()

    def submit(
        self,
        title: str,
        callable_: Callable[[], Any],
    ) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        job = {
            "id": job_id,
            "title": title,
            "status": "queued",
            "created_at": time.time(),
            "started_at": None,
            "completed_at": None,
            "result": None,
            "error": None,
            "callable": callable_,
        }
        with self._lock:
            self._jobs[job_id] = job
        self._queue.put(job)
        return self.public_job(job)

    def status(self) -> dict[str, Any]:
        with self._lock:
            jobs = [
                self.public_job(job)
                for job in self._jobs.values()
            ][-25:]
            current = (
                self.public_job(self._jobs[self._current_job_id])
                if self._current_job_id in self._jobs
                else None
            )
        return {
            "current": current,
            "queued": self._queue.qsize(),
            "jobs": jobs,
        }

    def shutdown(self) -> None:
        self._stop.set()
        self._queue.put({"sentinel": True})
        if self._worker.is_alive():
            self._worker.join(timeout=3.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            job = self._queue.get()
            if job.get("sentinel"):
                return

            job_id = job["id"]
            with self._lock:
                self._current_job_id = job_id
                job["status"] = "running"
                job["started_at"] = time.time()

            try:
                result = job["callable"]()
                with self._lock:
                    job["status"] = "complete"
                    job["result"] = result
            except Exception as exc:
                with self._lock:
                    job["status"] = "failed"
                    job["error"] = str(exc)
            finally:
                with self._lock:
                    job["completed_at"] = time.time()
                    self._current_job_id = None
                self._queue.task_done()

    @staticmethod
    def public_job(job: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in job.items()
            if key != "callable"
        }
