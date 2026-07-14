from rareiq.services.pipeline_state_service import PipelineStateService


def stages(snapshot):
    return {item["key"]: item for item in snapshot["stages"]}


def test_full_live_mapping():
    service = PipelineStateService()
    result = service.sync_from_snapshot({
        "camera": {"state": "running", "latest_crop_available": True},
        "recognition": {
            "busy": True,
            "collector_number": "239/204",
            "candidates": [{"id": "1"}, {"id": "2"}],
            "verification_state": "VERIFIED",
            "recognition_locked": True,
        },
        "recognition_state": {"card_detected": True, "crop_ready": True},
        "current_card": {"card_name": "Suicune ex"},
        "session": {"id": "session-1"},
    })
    mapped = stages(result)
    for key in (
        "camera","detect","crop","ocr",
        "artwork","verify","current_card","session"
    ):
        assert mapped[key]["state"] == "done"


def test_live_camera_waits_for_card():
    service = PipelineStateService()
    result = service.sync_from_snapshot({
        "camera": {"connected": True},
        "recognition": {},
        "recognition_state": {},
        "current_card": None,
        "session": {},
    })
    mapped = stages(result)
    assert mapped["camera"]["state"] == "done"
    assert mapped["detect"]["state"] == "running"
    assert mapped["crop"]["state"] == "waiting"
