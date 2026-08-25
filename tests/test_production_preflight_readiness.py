from rareiq.web.server import _program_camera_readiness


def _slot(
    slot_id: int,
    *,
    source_id: str | None = "camera-a",
    connected: bool = True,
    last_frame_at: float | None = 99.5,
    name: str = "Insta360 Link",
) -> dict:
    return {
        "slot_id": slot_id,
        "source_id": source_id,
        "connected": connected,
        "last_frame_at": last_frame_at,
        "display_name": name,
    }


def test_program_camera_requires_the_selected_slot_not_any_connected_preview() -> None:
    result = _program_camera_readiness(
        [
            _slot(1, connected=False, last_frame_at=None),
            _slot(2, source_id="camera-b", connected=True, last_frame_at=99.8),
        ],
        1,
        now=100.0,
    )

    assert result["ready"] is False
    assert result["state"] == "fail"
    assert "not connected" in result["detail"]


def test_program_camera_requires_a_fresh_frame() -> None:
    result = _program_camera_readiness([_slot(1, last_frame_at=97.0)], 1, now=100.0)

    assert result["ready"] is False
    assert result["frame_age_seconds"] == 3.0
    assert "stale" in result["detail"]


def test_program_camera_passes_with_current_frame_and_truthful_identity() -> None:
    result = _program_camera_readiness([_slot(1)], 1, now=100.0)

    assert result == {
        "ready": True,
        "state": "pass",
        "detail": "Program 1 · Insta360 Link · fresh frame",
        "action": "",
        "slot_id": 1,
        "frame_age_seconds": 0.5,
    }


def test_program_camera_reports_unassigned_slot_without_passing() -> None:
    result = _program_camera_readiness(
        [_slot(1, source_id=None, connected=False, last_frame_at=None)],
        1,
        now=100.0,
    )

    assert result["ready"] is False
    assert result["state"] == "warn"
    assert "no assigned camera" in result["detail"]
