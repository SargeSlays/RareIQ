from rareiq.services.reaction_asset_service import ReactionAssetService


PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 32
MP3 = b"ID3" + b"x" * 32


def test_reaction_assets_validate_store_and_map(tmp_path):
    service = ReactionAssetService(tmp_path / "assets", tmp_path / "state.json")
    visual = service.add("spark.png", "image/png", PNG)
    audio = service.add("hit.mp3", "audio/mpeg", MP3)
    assert visual["created"] and audio["created"]
    assert service.map_tier("grail", "visual", visual["asset"]["id"])["updated"]
    assert service.map_tier("grail", "audio", audio["asset"]["id"])["updated"]
    snapshot = ReactionAssetService(tmp_path / "assets", tmp_path / "state.json").snapshot()
    assert snapshot["mapping"]["grail"]["visual"]["name"] == "spark"
    assert snapshot["mapping"]["grail"]["audio"]["name"] == "hit"


def test_reaction_assets_reject_unsupported_spoofed_and_oversized_files(tmp_path):
    service = ReactionAssetService(tmp_path / "assets", tmp_path / "state.json")
    assert service.add("bad.svg", "image/svg+xml", b"<svg/>")["reason"] == "unsupported_media_type"
    assert service.add("fake.png", "image/png", b"not png")["reason"] == "file_signature_mismatch"
    assert service.add("huge.png", "image/png", PNG + b"x" * (8 * 1024 * 1024))["reason"] == "asset_too_large"


def test_reaction_mapping_guards_kind_and_path_lookup(tmp_path):
    service = ReactionAssetService(tmp_path / "assets", tmp_path / "state.json")
    visual = service.add("spark.png", "image/png", PNG)["asset"]
    assert service.map_tier("grail", "audio", visual["id"])["reason"] == "asset_kind_mismatch"
    assert service.get_path("../../settings") is None
