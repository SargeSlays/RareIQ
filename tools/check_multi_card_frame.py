"""Replay card geometry on a saved frame; never opens a camera or writes runtime data."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
import tempfile
from urllib.request import urlopen

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rareiq.services.multi_card_recognition_service import SixCardGridDetector


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path, nargs="?")
    parser.add_argument("--current-preview", action="store_true", help="Read one frame from the already-running loopback preview; never starts a camera.")
    parser.add_argument("--preview-dir", type=Path, help="Save this frame and detected crops for offline diagnosis.")
    parser.add_argument("--recognize", action="store_true", help="Replay the saved frame against local indexes with temporary scan storage; no live state or output changes.")
    parser.add_argument("--region", nargs=4, type=int, metavar=("LEFT", "TOP", "RIGHT", "BOTTOM"))
    parser.add_argument("--max-cards", type=int, default=12, choices=range(2, 13))
    parser.add_argument("--debug-contours", action="store_true")
    args = parser.parse_args()
    if bool(args.image) == args.current_preview:
        parser.error("Choose an image or --current-preview.")
    if args.current_preview:
        data = bytearray()
        deadline = time.monotonic() + 10
        with urlopen("http://127.0.0.1:9040/api/camera/stream", timeout=5) as response:
            while len(data) < 16 * 1024 * 1024 and time.monotonic() < deadline:
                chunk = response.read(4096)
                if not chunk:
                    break
                data.extend(chunk)
                start, end = data.find(b"\xff\xd8"), data.find(b"\xff\xd9")
                if 0 <= start < end:
                    break
        start, end = data.find(b"\xff\xd8"), data.find(b"\xff\xd9")
        if not 0 <= start < end:
            parser.error("No complete preview frame was received.")
        frame = cv2.imdecode(np.frombuffer(data[start:end + 2], dtype=np.uint8), cv2.IMREAD_COLOR)
    else:
        frame = cv2.imread(str(args.image))
    if frame is None:
        parser.error("The frame could not be read.")
    if args.region:
        left, top, right, bottom = args.region
        height, width = frame.shape[:2]
        if not (0 <= left < right <= width and 0 <= top < bottom <= height):
            parser.error("The region must be inside the supplied image.")
        frame = frame[top:bottom, left:right]
    if args.debug_contours:
        gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (5, 5), 0)
        median = float(np.median(gray))
        lower = int(max(18, median * .55))
        edges = cv2.Canny(gray, lower, int(min(235, max(lower + 35, median * 1.45))))
        _, light = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        for name, mask in (("edges", edges), ("light", light)):
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), dtype=np.uint8), iterations=2)
            contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            summaries = []
            for contour in contours:
                (cx, cy), (w, h), _ = cv2.minAreaRect(contour)
                area = w * h / gray.size
                if .025 < area < .4 and min(w, h) > 0:
                    quad = cv2.approxPolyDP(contour, .02 * cv2.arcLength(contour, True), True)
                    summaries.append({"area": round(area, 3), "aspect": round(max(w, h)/min(w,h), 2),
                                      "fill": round(cv2.contourArea(contour)/(w*h), 2), "corners": len(quad),
                                      "center": [round(cx/frame.shape[1], 3), round(cy/frame.shape[0], 3)]})
            print(name, json.dumps(sorted(summaries, key=lambda item: -item["area"])))
    started = time.perf_counter()
    results = SixCardGridDetector.detect(frame, max_cards=args.max_cards)
    if args.preview_dir:
        args.preview_dir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(args.preview_dir / "frame.png"), frame)
        for item in results:
            cv2.imwrite(str(args.preview_dir / f"slot-{item['slot']}.png"), item["crop"])
    print(json.dumps({
        "frame_size": [frame.shape[1], frame.shape[0]],
        "detected_count": len(results),
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
        "slots": [{key: item[key] for key in ("slot", "confidence", "centroid", "polygon")} for item in results],
    }, indent=2))
    if args.recognize:
        from rareiq.services.recognition_service import RecognitionService
        from rareiq.services.multi_card_recognition_service import MultiCardRecognitionService
        from rareiq.services.global_visual_index_service import GlobalVisualIndexService
        from rareiq.services.vision_optimizer_service import VisionOptimizerService
        from rareiq.services.candidate_ranker_service import CandidateRankerService
        from rareiq.services.recognition_fusion_service import RecognitionFusionService
        from rareiq.services.recognition_diagnostics_service import RecognitionDiagnosticsService

        prototype = RecognitionService(lambda _event: None)
        prototype.set_global_visual_index(GlobalVisualIndexService(Path(__file__).resolve().parents[1], None))
        prototype.set_intelligence_services(VisionOptimizerService(), CandidateRankerService(RecognitionFusionService()), RecognitionDiagnosticsService())
        with tempfile.TemporaryDirectory(prefix="rareiq-saved-frame-") as directory:
            service = MultiCardRecognitionService(prototype, Path(directory) / "history.json", Path(directory) / "presentation.json")
            try:
                recognition_started = time.perf_counter()
                state = service.capture(frame, max_cards=args.max_cards, detections=results)
                deadline = time.monotonic() + 125
                while state["status"] == "recognizing" and time.monotonic() < deadline:
                    time.sleep(.2)
                    state = service.status()
                print(json.dumps({"status": state["status"], "verified_count": state["verified_count"],
                                  "recognition_elapsed_ms": round((time.perf_counter() - recognition_started) * 1000, 1),
                                  "reconciliation_timings": state.get("reconciliation_timings"),
                                  "slots": [{"slot": item["slot"], "status": item["status"],
                                             "card": {key: (item.get("card") or {}).get(key) for key in (
                                                 "name", "canonical_name", "collector_number", "language", "reference_image_url")},
                                             "observed_number": item.get("collector_number"),
                                             "observed_name": item.get("name_candidate"),
                                             "observed_language": item.get("language"),
                                             "stage_timings": item.get("stage_timings"),
                                             "raw_text": [{key: entry.get(key) for key in ("text", "score", "source", "variant")}
                                                          for entry in item.get("raw_text") or []],
                                             "ocr_mode": (item.get("stage_timings") or {}).get("ocr_mode")}
                                      for item in state["slots"] if item.get("polygon")]}, indent=2, ensure_ascii=False))
            finally:
                service.shutdown()
                prototype.shutdown()


if __name__ == "__main__":
    main()
