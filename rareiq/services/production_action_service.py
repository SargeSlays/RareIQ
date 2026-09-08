"""Bounded, process-local dispatch for explicitly registered operator actions.

Adapters own outcome verification. A timeout is pending, never proof of failure;
the same request ID observes the original work instead of starting it again.
"""
from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from copy import deepcopy
from dataclasses import dataclass
import json
import math
import threading
import time
from typing import Any, Callable
import uuid


@dataclass(frozen=True)
class ActionSpec:
    action_id: str
    validate: Callable[[dict[str, Any]], dict[str, Any]]
    execute: Callable[[dict[str, Any]], dict[str, Any]]
    capability: str
    timeout_seconds: float = 15


class ProductionActions:
    def __init__(self, *, capacity: int = 2, retained: int = 128) -> None:
        self._specs: dict[str, ActionSpec] = {}
        self._requests: OrderedDict[str, tuple[str, Future, float]] = OrderedDict()
        self._lock = threading.RLock()
        self._pool = ThreadPoolExecutor(max_workers=capacity, thread_name_prefix="production-action")
        self._capacity, self._retained = capacity, retained

    def register(self, spec: ActionSpec) -> None:
        if spec.action_id in self._specs:
            raise ValueError("duplicate_action")
        self._specs[spec.action_id] = spec

    def manifest(self) -> list[dict[str, Any]]:
        return [{"id": item.action_id, "capability": item.capability,
                 "risk": "production", "timeout_seconds": item.timeout_seconds}
                for item in self._specs.values()]

    @staticmethod
    def _result(state: str, reason: str, **details: Any) -> dict[str, Any]:
        return {"ok": False, "state": state, "reason": reason, **details}

    def dispatch(self, action_id: str, params: dict[str, Any], *, origin: str,
                 request_id: str | None = None, expires_at: float | None = None,
                 practice: bool = False) -> dict[str, Any]:
        # Origin is supplied by a trusted host adapter, never inferred from text.
        if origin not in {"operator", "host_voice"}:
            return self._result("rejected", "untrusted_action_origin")
        spec = self._specs.get(action_id)
        if spec is None:
            return self._result("rejected", "unknown_action")
        if request_id and expires_at is None:
            return self._result("rejected", "request_expiry_required")
        if expires_at is not None and (not isinstance(expires_at, (int, float)) or isinstance(expires_at, bool) or not math.isfinite(expires_at) or expires_at <= time.time() or expires_at > time.time() + 120):
            return self._result("rejected", "action_expired")
        try:
            normalized = spec.validate(deepcopy(params))
            fingerprint = json.dumps([action_id, origin, normalized, expires_at], sort_keys=True, allow_nan=False)
        except (ValueError, TypeError, KeyError):
            return self._result("rejected", "invalid_action_parameters")
        if practice:
            return {"ok": True, "state": "validated", "executed": False, "action_id": action_id}
        key = request_id or uuid.uuid4().hex
        if not isinstance(key, str) or not 1 <= len(key) <= 80 or not all(c.isalnum() or c in "_-" for c in key):
            return self._result("rejected", "invalid_request_id")
        with self._lock:
            previous = self._requests.get(key)
            if previous:
                if previous[0] != fingerprint:
                    return self._result("rejected", "request_id_conflict")
                future = previous[1]
            else:
                if sum(not item[1].done() for item in self._requests.values()) >= self._capacity:
                    return self._result("rejected", "action_capacity_reached")
                for old, item in list(self._requests.items()):
                    if item[1].done() and item[2] <= time.time():
                        self._requests.pop(old)
                if len(self._requests) >= self._retained:
                    return self._result("rejected", "action_capacity_reached")
                future = self._pool.submit(spec.execute, normalized)
                self._requests[key] = (fingerprint, future, time.time() + 120)
        try:
            payload = deepcopy(future.result(timeout=spec.timeout_seconds))
            ok = payload.get("ok") is True
            return {"ok": ok, "state": "succeeded" if ok else "failed", "request_id": key,
                    "action_id": action_id, "result": payload}
        except TimeoutError:
            if future.done():
                return self._result("failed", "action_adapter_failed", request_id=key, action_id=action_id)
            return self._result("executing", "action_still_running", request_id=key, action_id=action_id)
        except Exception:
            # Never return adapter exception strings: they may contain host paths or secrets.
            return self._result("failed", "action_adapter_failed", request_id=key, action_id=action_id)

    def close(self) -> None:
        self._pool.shutdown(wait=True, cancel_futures=True)
