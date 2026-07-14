from rareiq.services.pipeline_state_service import PipelineStateService


def test_pipeline_state_lifecycle():
    state = PipelineStateService()

    initial = state.snapshot()
    assert initial["phase"] == "waiting"
    assert initial["total_stages"] == 8

    state.start("detect", "Detecting card", frame_id=42)
    running = state.snapshot()
    assert running["phase"] == "detect"
    assert running["active_stage"]["frame_id"] == 42

    state.complete("detect", "Card detected", frame_id=42)
    complete = state.snapshot()
    detect = next(stage for stage in complete["stages"] if stage["key"] == "detect")
    assert detect["state"] == "done"
    assert detect["duration_ms"] >= 0


def test_pipeline_state_failure():
    state = PipelineStateService()
    state.start("ocr", "Reading")
    state.fail("ocr", "collector number unreadable")

    snapshot = state.snapshot()
    assert snapshot["phase"] == "failed"
    assert snapshot["failed_stage"]["key"] == "ocr"
    assert snapshot["failed_stage"]["error"] == "collector number unreadable"


def test_runtime_sync():
    state = PipelineStateService()
    snapshot = state.sync_from_runtime(
        camera={"visible": True},
        recognition={
            "busy": False,
            "card_detected": True,
            "latest_crop_available": True,
            "collector_number": "239/204",
            "candidates": [{"id": "1"}],
            "recognition_locked": True,
        },
        current_card={"card_name": "Suicune ex"},
    )

    states = {stage["key"]: stage["state"] for stage in snapshot["stages"]}
    assert states["camera"] == "done"
    assert states["detect"] == "done"
    assert states["crop"] == "done"
    assert states["ocr"] == "done"
    assert states["artwork"] == "done"
    assert states["verify"] == "done"
    assert states["current_card"] == "done"
