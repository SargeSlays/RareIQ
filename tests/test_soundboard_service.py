from rareiq.services.reaction_asset_service import ReactionAssetService


def wav_bytes():
    return b"RIFF" + (36).to_bytes(4, "little") + b"WAVE" + b"fmt " + b"\0" * 24


def test_soundboard_maps_uploaded_audio_and_persists(tmp_path):
    service = ReactionAssetService(tmp_path / "assets", tmp_path / "assets.json")
    created = service.add("air horn.wav", "audio/wav", wav_bytes())
    assert created["created"] is True
    asset_id = created["asset"]["id"]
    result = service.configure_soundboard([{"id": "horn", "label": "Air Horn", "asset_id": asset_id}])
    assert result["updated"] is True
    assert result["soundboard"][0]["asset"]["url"].endswith(asset_id)
    restored = ReactionAssetService(tmp_path / "assets", tmp_path / "assets.json").snapshot()
    assert restored["soundboard"][0]["label"] == "Air Horn"

def test_soundboard_pad_can_have_independent_button_image(tmp_path):
    service = ReactionAssetService(tmp_path / "assets", tmp_path / "assets.json")
    audio = service.add("horn.wav", "audio/wav", wav_bytes())["asset"]
    png = b"\x89PNG\r\n\x1a\n" + b"image"
    image = service.add("horn.png", "image/png", png)["asset"]
    configured = service.configure_soundboard([{"label": "Horn", "asset_id": audio["id"], "image_asset_id": image["id"]}])
    assert configured["updated"] is True
    assert configured["soundboard"][0]["image_asset"]["url"].endswith(image["id"])


def test_soundboard_rejects_visual_or_missing_assets(tmp_path):
    service = ReactionAssetService(tmp_path / "assets", tmp_path / "assets.json")
    result = service.configure_soundboard([{"label": "Bad", "asset_id": "missing"}])
    assert result == {"updated": False, "reason": "audio_asset_not_found"}


def test_soundboard_is_limited_to_fifty_pads(tmp_path):
    service = ReactionAssetService(tmp_path / "assets", tmp_path / "assets.json")
    result = service.configure_soundboard([{"label": f"Pad {index}"} for index in range(60)])
    assert result["updated"] is True
    assert len(result["soundboard"]) == 50
