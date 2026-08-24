from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def fetch_json(url: str, timeout: float = 3.0) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, timeout: float = 5.0) -> dict[str, Any]:
    request = urllib.request.Request(url, data=b"", method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * fraction)))
    return round(ordered[position], 2)


def summarize(samples: list[dict[str, Any]], camera: dict[str, Any]) -> dict[str, Any]:
    latencies = [float(item["latency_ms"]) for item in samples if item.get("latency_ms") is not None]
    capture_latencies = [
        float(item["capture_to_result_ms"])
        for item in samples
        if item.get("capture_to_result_ms") is not None
    ]
    fast_count = sum(item.get("recognition_path") == "fast" for item in samples)
    locked_count = sum(bool(item.get("recognition_locked")) for item in samples)
    unverified_lock_count = sum(
        bool(item.get("recognition_locked"))
        and item.get("verification_state") != "VERIFIED"
        for item in samples
    )
    return {
        "ok": bool(samples),
        "camera": camera,
        "sample_count": len(samples),
        "fast_path_count": fast_count,
        "fast_path_rate": round(fast_count / len(samples), 4) if samples else 0.0,
        "locked_count": locked_count,
        "unverified_lock_count": unverified_lock_count,
        "latency_ms": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "max": round(max(latencies), 2) if latencies else None,
        },
        "capture_to_result_ms": {
            "p50": percentile(capture_latencies, 0.50),
            "p95": percentile(capture_latencies, 0.95),
        },
        "samples": samples,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect live Stream-Speed recognition telemetry.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--duration-seconds", type=float, default=120.0)
    parser.add_argument("--interval-seconds", type=float, default=0.25)
    parser.add_argument(
        "--rearm-seconds", type=float, default=0.0,
        help="Operator-clear recognition at this interval; 0 disables automatic rearming.",
    )
    parser.add_argument("--include-existing", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    try:
        camera = fetch_json(f"{base_url}/api/camera/status")
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"RareIQ runtime unavailable at {base_url}: {exc}")
        return 2

    manager = camera.get("manager") or {}
    vision = camera.get("vision") or {}
    if not manager.get("worker_alive") or not vision.get("frame_available"):
        report = {
            "ok": False,
            "reason": "camera_not_ready",
            "base_url": base_url,
            "camera": camera,
            "sample_count": 0,
            "error": manager.get("last_error") or vision.get("error"),
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({
            "ok": False,
            "reason": report["reason"],
            "error": report["error"],
        }, indent=2))
        return 3

    samples: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any]] = set()
    if not args.include_existing:
        existing = fetch_json(f"{base_url}/api/recognition/status").get("recognition") or {}
        seen.add((existing.get("updated_at"), existing.get("artwork_fingerprint")))
    deadline = time.monotonic() + max(0.0, args.duration_seconds)
    next_rearm = (
        time.monotonic() + args.rearm_seconds if args.rearm_seconds > 0 else None
    )
    while time.monotonic() < deadline:
        if next_rearm is not None and time.monotonic() >= next_rearm:
            try:
                post_json(f"{base_url}/api/recognition/clear")
            except (OSError, urllib.error.URLError, json.JSONDecodeError):
                pass
            next_rearm = time.monotonic() + args.rearm_seconds
        try:
            status = fetch_json(f"{base_url}/api/recognition/status").get("recognition") or {}
            key = (status.get("updated_at"), status.get("artwork_fingerprint"))
            if status.get("updated_at") is not None and key not in seen:
                seen.add(key)
                timings = status.get("stage_timings") or {}
                samples.append({
                    "observed_at": time.time(),
                    "updated_at": status.get("updated_at"),
                    "recognition_path": status.get("recognition_path"),
                    "recognition_locked": bool(status.get("recognition_locked")),
                    "verification_state": status.get("verification_state"),
                    "collector_number": status.get("collector_number"),
                    "language": status.get("language"),
                    "confidence": status.get("overall_confidence"),
                    "latency_ms": status.get("last_latency_ms"),
                    "capture_to_result_ms": timings.get("capture_to_result_ms"),
                    "skipped_stages": timings.get("skipped_stages") or [],
                    "stage_timings": timings,
                    "fast_path": status.get("fast_path"),
                    "top_candidate": next(iter(
                        (status.get("artwork_index") or {}).get("matches") or []
                    ), None),
                    "fast_identity_cache": (
                        ((status.get("artwork_index") or {}).get("status") or {})
                        .get("fast_identity_cache")
                    ),
                })
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            pass
        time.sleep(max(0.05, args.interval_seconds))

    report = summarize(samples, camera)
    report["duration_seconds"] = args.duration_seconds
    report["base_url"] = base_url
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "ok", "sample_count", "fast_path_count", "fast_path_rate",
        "locked_count", "unverified_lock_count", "latency_ms", "capture_to_result_ms",
    )}, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
