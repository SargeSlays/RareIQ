from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rareiq.services.artwork_index_service import ArtworkIndexService
from rareiq.services.global_visual_index_service import GlobalVisualIndexService
from rareiq.services.stream_speed_benchmark_service import StreamSpeedBenchmarkService


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay captures through the Stream-Speed gate.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-p95-ms", type=float, default=250.0)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    samples = list(manifest.get("samples") or [])
    for sample in samples:
        path = Path(str(sample.get("path") or ""))
        if not path.is_absolute():
            sample["path"] = str((PROJECT_ROOT / path).resolve())

    global_index = GlobalVisualIndexService(PROJECT_ROOT, catalog_engine=None)
    artwork_index = ArtworkIndexService()
    report = StreamSpeedBenchmarkService(global_index, artwork_index).run(
        samples, target_p95_ms=args.target_p95_ms
    )
    report["manifest"] = str(args.manifest.resolve())
    report["index_status"] = {
        "global_visual": global_index.status(),
        "artwork": artwork_index.status(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "ok", "sample_count", "successful_count", "labeled_sample_count",
        "unlabeled_sample_count", "label_coverage_rate", "fast_path_eligible_count",
        "fast_path_eligible_rate", "labeled_fast_path_count", "false_lock_count",
        "latency_ms", "gates",
    )}, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
