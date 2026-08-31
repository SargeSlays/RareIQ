import asyncio
import json
from types import SimpleNamespace

import pytest

from rareiq.services.reaction_asset_service import ReactionAssetService
from rareiq.web import server


@pytest.fixture
def assets(tmp_path):
    service = ReactionAssetService(tmp_path / "assets", tmp_path / "assets.json")
    sound = service.add("horn.mp3", "audio/mpeg", b"ID3" + b"test" * 10)["asset"]
    service.configure_soundboard([{"id": "horn", "label": "Horn", "asset_id": sound["id"]}])
    service.map_tier("grail", "audio", sound["id"])
    return service, sound


@pytest.mark.parametrize("operation", ["pad", "mapping", "upload"])
def test_failed_asset_settings_save_preserves_runtime_and_disk(assets, monkeypatch, operation):
    service, sound = assets
    before = service.snapshot()
    disk = service.state_path.read_bytes()
    files = sorted(service.root.rglob("*"))
    def failed():
        raise OSError("storage unavailable")
    monkeypatch.setattr(service, "_persist", failed)
    with pytest.raises(OSError):
        if operation == "pad":
            service.configure_soundboard([{"id": "changed", "label": "Changed", "asset_id": sound["id"]}])
        elif operation == "mapping":
            service.map_tier("grail", "audio", None)
        else:
            service.add("new.mp3", "audio/mpeg", b"ID3" + b"audio")
    assert service.snapshot() == before
    assert service.state_path.read_bytes() == disk
    assert sorted(service.root.rglob("*")) == files


def test_missing_audio_is_not_advertised_as_playable(assets):
    service, sound = assets
    path, _mime = service.get_path(sound["id"])
    path.unlink()
    snapshot = service.snapshot()
    assert snapshot["assets"] == []
    assert snapshot["soundboard"][0]["asset"] is None
    assert snapshot["mapping"]["grail"]["audio"] is None
    assert service.configure_soundboard([{"asset_id": sound["id"]}])["updated"] is False
    assert service.map_tier("low", "audio", sound["id"])["updated"] is False


def test_duplicate_pad_ids_are_rejected_without_changing_configuration(assets):
    service, sound = assets
    before = service.snapshot()
    result = service.configure_soundboard([{"id": "same", "asset_id": sound["id"]}] * 2)
    assert result == {"updated": False, "reason": "duplicate_pad_id"}
    assert service.snapshot() == before


@pytest.mark.parametrize("payload", [[], None, {"assets": {"bad": None}}, {"assets": {"bad": {"id": "bad", "path": "missing"}}, "soundboard": [None, 2]}])
def test_malformed_saved_assets_do_not_break_soundboard_startup(tmp_path, payload):
    state = tmp_path / "state.json"
    state.write_text(json.dumps(payload), encoding="utf-8")
    service = ReactionAssetService(tmp_path / "assets", state)
    assert service.snapshot()["assets"] == []


def test_outside_root_asset_is_unavailable_in_both_snapshot_and_file_route(assets, tmp_path):
    service, sound = assets
    outside = tmp_path / "unrelated.mp3"
    outside.write_bytes(b"ID3private")
    saved = json.loads(service.state_path.read_text())
    saved["assets"][sound["id"]]["path"] = str(outside)
    service.state_path.write_text(json.dumps(saved), encoding="utf-8")
    restored = ReactionAssetService(service.root, service.state_path)
    assert restored.get_path(sound["id"]) is None
    assert restored.snapshot()["assets"] == []
    assert restored.snapshot()["soundboard"][0]["asset"] is None


def test_soundboard_api_reports_storage_failure_and_keeps_configuration(assets, monkeypatch):
    service, _sound = assets
    before = service.snapshot()
    monkeypatch.setattr(server, "orchestrator", SimpleNamespace(reaction_assets=service))
    def failed():
        raise OSError("storage unavailable")
    monkeypatch.setattr(service, "_persist", failed)
    response = asyncio.run(server.configure_soundboard(server.SoundboardConfigRequest(pads=[])))
    assert response.status_code == 409
    assert json.loads(response.body)["reason"] == "asset_storage_unavailable"
    assert service.snapshot() == before
