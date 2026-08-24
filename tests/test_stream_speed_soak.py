from tools.soak_stream_speed import percentile, summarize


def test_soak_summary_reports_fast_rate_and_latency_percentiles():
    samples = [
        {"recognition_path": "full", "recognition_locked": True, "latency_ms": 300, "capture_to_result_ms": 340},
        {"recognition_path": "fast", "recognition_locked": True, "latency_ms": 40, "capture_to_result_ms": 55},
        {"recognition_path": "fast", "recognition_locked": False, "latency_ms": 60, "capture_to_result_ms": 70},
    ]
    report = summarize(samples, {"manager": {"state": "running"}})
    assert report["ok"] is True
    assert report["fast_path_rate"] == 0.6667
    assert report["locked_count"] == 2
    assert report["unverified_lock_count"] == 2
    assert report["latency_ms"] == {"p50": 60.0, "p95": 60.0, "max": 300.0}
    assert percentile([], 0.95) is None
