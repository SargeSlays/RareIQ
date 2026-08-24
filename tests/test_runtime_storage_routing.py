from pathlib import Path
import time

from rareiq.services.instant_replay_service import InstantReplayService


SERVER = Path("rareiq/web/server.py").read_text(encoding="utf-8")


def test_large_runtime_media_uses_configured_storage_roots():
    assert 'storage.get_path("provenance_path")' in SERVER
    assert 'storage.get_path("replay_path")' in SERVER
    assert 'storage.get_path("recording_path")' in SERVER
    assert 'config_path=storage.get_path("config_path") / "recording_settings.json"' in SERVER


def test_repository_provenance_is_read_only_legacy_compatibility():
    assert 'legacy_roots=(BASE_DIR.parent / "data" / "provenance",)' in SERVER
    assert 'ProvenanceCaptureService(\n    BASE_DIR.parent / "data" / "provenance"' not in SERVER


def test_replays_and_recordings_no_longer_write_to_repository_roots():
    assert 'InstantReplayService(BASE_DIR.parent.parent / "replays"' not in SERVER
    assert 'RecordingService(BASE_DIR.parent.parent / "recordings")' not in SERVER


def test_replay_retention_removes_evicted_highlight_files(tmp_path):
    service = InstantReplayService(
        tmp_path / "replays",
        frame_provider=lambda _slot: None,
        program_slot_provider=lambda: 1,
        fps=1,
        buffer_seconds=2,
    )
    paths = []
    for index in range(service.MAX_HIGHLIGHTS + 1):
        service._frames.clear()
        service._frames.append((time.time(), 1, f"jpeg-{index}".encode("ascii")))
        result = service.mark(seconds=2, name=f"Highlight {index}")
        assert result["created"] is True
        paths.append(next(path for path in service.root.iterdir() if path.is_dir() and path not in paths))

    assert len(service.snapshot()["highlights"]) == service.MAX_HIGHLIGHTS
    assert paths[0].exists() is False
    assert all(path.is_dir() for path in paths[1:])
