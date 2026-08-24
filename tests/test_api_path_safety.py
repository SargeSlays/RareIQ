from __future__ import annotations

import json

from rareiq.services.instant_replay_service import InstantReplayService
from rareiq.services.inventory_service import InventoryService


def _replay(root):
    return InstantReplayService(
        root,
        frame_provider=lambda _slot: None,
        program_slot_provider=lambda: 1,
    )


def test_replay_reload_rejects_highlight_directories_outside_replay_root(tmp_path):
    replay_root = tmp_path / "replays"
    replay_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "0000.jpg").write_bytes(b"private")
    (replay_root / "highlights.json").write_text(
        json.dumps([{"id": "escaped", "path": str(outside), "frames": 1}]),
        encoding="utf-8",
    )

    service = _replay(replay_root)

    assert service.snapshot()["highlights"] == []
    assert service.frame("escaped", 0) is None


def test_replay_reload_ignores_malformed_highlight_without_identifier(tmp_path):
    replay_root = tmp_path / "replays"
    highlight = replay_root / "highlight-a"
    highlight.mkdir(parents=True)
    (replay_root / "highlights.json").write_text(
        json.dumps([{"path": str(highlight), "frames": 1}]),
        encoding="utf-8",
    )

    service = _replay(replay_root)

    assert service.snapshot()["highlights"] == []
    assert service.frame("missing", 0) is None


def test_replay_serves_only_frames_inside_a_valid_highlight_directory(tmp_path):
    replay_root = tmp_path / "replays"
    highlight = replay_root / "highlight-a"
    highlight.mkdir(parents=True)
    frame = highlight / "0000.jpg"
    frame.write_bytes(b"jpeg")
    (replay_root / "highlights.json").write_text(
        json.dumps([{"id": "valid", "path": str(highlight), "frames": 1}]),
        encoding="utf-8",
    )

    service = _replay(replay_root)

    assert service.frame("valid", 0) == frame.resolve()


def test_inventory_receipt_lookup_rejects_relative_and_absolute_escapes(tmp_path):
    service = InventoryService(tmp_path / "inventory.json")
    outside = tmp_path / "private.pdf"
    outside.write_bytes(b"private")

    for expense_id, receipt in (
        ("EXP-RELATIVE", "../private.pdf"),
        ("EXP-ABSOLUTE", str(outside.resolve())),
    ):
        service._expenses[expense_id] = {
            "expense_id": expense_id,
            "receipt_file": receipt,
            "incurred_at": 0,
        }
        assert service.expense_receipt(expense_id) is None
        assert service._expense_public(service._expenses[expense_id])["receipt_url"] is None


def test_removing_tampered_expense_cannot_delete_file_outside_receipt_root(tmp_path):
    service = InventoryService(tmp_path / "inventory.json")
    outside = tmp_path / "do-not-delete.pdf"
    outside.write_bytes(b"private")
    service._expenses["EXP-ESCAPE"] = {
        "expense_id": "EXP-ESCAPE",
        "receipt_file": "../do-not-delete.pdf",
        "incurred_at": 0,
        "category": "other",
        "amount": 1,
    }

    assert service.remove_expense("EXP-ESCAPE")["removed"] is True
    assert outside.read_bytes() == b"private"


def test_valid_inventory_receipt_remains_readable_and_deletable(tmp_path):
    service = InventoryService(tmp_path / "inventory.json")
    receipt_root = tmp_path / "expense_receipts"
    receipt_root.mkdir()
    receipt = receipt_root / "EXP-VALID.png"
    receipt.write_bytes(b"png")
    service._expenses["EXP-VALID"] = {
        "expense_id": "EXP-VALID",
        "receipt_file": receipt.name,
        "incurred_at": 0,
        "category": "supplies",
        "amount": 1,
    }

    assert service.expense_receipt("EXP-VALID") == receipt.resolve()
    assert service.remove_expense("EXP-VALID")["removed"] is True
    assert not receipt.exists()
