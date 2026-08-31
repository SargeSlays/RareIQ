"""Exercise real OBS outputs without changing Program or starting a recording.

Use --wire-audio to add the shared soundboard scene to RareIQ's own visual
scenes. Never touches unrelated operator scenes or input devices.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import uuid
from pathlib import Path

import httpx
import obsws_python
from obsws_python.subs import Subs

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rareiq.services.obs_service import ObsService


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:9040")
    parser.add_argument("--wire-audio", action="store_true")
    parser.add_argument("--meter-seconds", type=float, default=8)
    args = parser.parse_args()
    service = ObsService(ROOT / "obs_settings.json")
    report = {"sources": [], "audio_links": [], "audio_peak": 0.0}
    screenshots = ROOT / "artifacts" / "broadcast-outputs"
    screenshots.mkdir(parents=True, exist_ok=True)
    owner, sequence = "output-check-" + uuid.uuid4().hex, 0
    with httpx.Client(base_url=args.base_url, timeout=10) as http, service._connection() as obs:
        program = obs.get_scene_list().current_program_scene_name
        studio = obs.get_studio_mode_enabled().studio_mode_enabled
        preview = obs.get_current_preview_scene().current_preview_scene_name if studio else None
        assert not obs.get_stream_status().output_active, "Do not run output tests during a live stream"
        assert not obs.get_record_status().output_active, "Do not run output tests during a recording"
        for item in service.bootstrap_plan(args.base_url):
            settings = obs.get_input_settings(item["source"]).input_settings
            assert settings["url"] == item["url"], item["source"]
            if item.get("audio"):
                assert settings.get("reroute_audio") is True
                assert not settings.get("shutdown", False)
            if "/output/camera/" in item["url"]:
                obs.press_input_properties_button(item["source"], "refreshnocache")
            report["sources"].append({"name": item["source"], "url": settings["url"], "audio": bool(settings.get("reroute_audio"))})
        if args.wire_audio:
            for scene in [item["scene"] for item in service.bootstrap_plan(args.base_url) if not item.get("audio")]:
                items = obs.get_scene_item_list(scene).scene_items
                if not any(item.get("sourceName") == "RareIQ Soundboard" for item in items):
                    obs.create_scene_item(scene, "RareIQ Soundboard", True)
                    report["audio_links"].append(scene)
        config = service._config
        with obsws_python.EventClient(host=config["host"], port=config["port"], password=config.get("password") or "", subs=Subs.INPUTVOLUMEMETERS) as events:
            heard = threading.Event()
            def on_input_volume_meters(event):
                for value in event.inputs:
                    if value.get("inputName") == "RareIQ Soundboard Audio":
                        peak = max((level for channel in value.get("inputLevelsMul", []) for level in channel), default=0)
                        report["audio_peak"] = max(report["audio_peak"], peak)
                        if peak > 0:
                            heard.set()
            events.callback.register(on_input_volume_meters)
            test_item = None
            try:
                obs.press_input_properties_button("RareIQ Soundboard Audio", "refreshnocache")
                if not studio and not any(item.get("sourceName") == "RareIQ Soundboard" for item in obs.get_scene_item_list(program).scene_items):
                    test_item = obs.create_scene_item(program, "RareIQ Soundboard", True).scene_item_id
                obs.set_studio_mode_enabled(True)
                for scene, filename in [("RareIQ Scan Camera", "scan-camera.png"), ("RareIQ All Cameras", "all-cameras.png")]:
                    obs.set_current_preview_scene(scene)
                    time.sleep(2)
                    obs.save_source_screenshot(scene, "png", str(screenshots / filename), 1920, 1080, -1)
                obs.set_current_preview_scene("RareIQ Soundboard")
                # OBS meters only active Program audio. Temporarily reference the
                # transparent shared audio scene; no visual scene switch occurs.
                active = obs.get_source_active("RareIQ Soundboard Audio")
                report["audio_source_active"] = {"video_active":active.video_active,"video_showing":active.video_showing}
                report["audio_muted"] = obs.get_input_mute("RareIQ Soundboard Audio").input_muted
                assets = http.get("/api/soundboard").json()["assets"]
                asset = next((a for a in assets if a["kind"] == "audio"), None)
                if asset:
                    start = time.monotonic()
                    while time.monotonic() - start < args.meter_seconds and not heard.is_set():
                        sequence += 1
                        response = http.post("/api/output/soundboard", json={"owner":owner,"sequence":sequence,"voices":[{"id":"meter-test","asset_id":asset["id"],"position":15+time.monotonic()-start,"volume":.03}]})
                        response.raise_for_status()
                        report["audio_receivers"] = response.json()["receivers"]
                        heard.wait(.25)
                    report["audio_meter_verified"] = heard.is_set()
                else:
                    report["audio_meter_verified"] = False
                    report["audio_test_note"] = "No saved soundboard audio available"
            finally:
                http.post("/api/output/soundboard", json={"owner":owner,"sequence":sequence+1,"voices":[]})
                if test_item is not None:
                    obs.remove_scene_item(program, test_item)
                if preview:
                    obs.set_current_preview_scene(preview)
                obs.set_studio_mode_enabled(studio)
        report["program_unchanged"] = obs.get_scene_list().current_program_scene_name == program
        report["streaming"] = obs.get_stream_status().output_active
        report["recording"] = obs.get_record_status().output_active
    (screenshots / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report.get("audio_meter_verified") and report["program_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
