from __future__ import annotations

import asyncio
import base64

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from rareiq.services.inventory_service import (
    MAX_RECEIPT_BASE64_CHARS,
    MAX_RECEIPT_DATA_URL_CHARS,
    InventoryService,
)
from rareiq.web.server import (
    MAX_CONTROL_REQUEST_BYTES,
    InventoryExpenseRequest,
    RequestBodyTooLarge,
    _read_bounded_body,
    app,
    orchestrator,
)


def _streaming_request(chunks: list[bytes], headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    messages = [
        {"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1}
        for index, chunk in enumerate(chunks)
    ] or [{"type": "http.request", "body": b"", "more_body": False}]

    async def receive():
        return messages.pop(0)

    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/upload",
            "raw_path": b"/upload",
            "query_string": b"",
            "headers": headers or [],
            "client": ("test", 1),
            "server": ("test", 80),
        },
        receive,
    )


def test_bounded_reader_rejects_declared_size_before_reading_body():
    request = _streaming_request(
        [b"never-read"],
        [(b"content-length", str(MAX_CONTROL_REQUEST_BYTES + 1).encode("ascii"))],
    )

    with pytest.raises(RequestBodyTooLarge):
        asyncio.run(_read_bounded_body(request, MAX_CONTROL_REQUEST_BYTES))


def test_bounded_reader_rejects_chunked_body_as_soon_as_limit_is_crossed():
    request = _streaming_request([b"1234", b"5678", b"9"])

    with pytest.raises(RequestBodyTooLarge):
        asyncio.run(_read_bounded_body(request, 8))


def test_creator_asset_route_returns_413_from_declared_oversize(monkeypatch):
    limit = orchestrator.reaction_assets.ALLOWED["image/png"][2]
    called = False

    def unexpected_add(*_args, **_kwargs):
        nonlocal called
        called = True
        return {"created": True}

    monkeypatch.setattr(orchestrator.reaction_assets, "add", unexpected_add)
    response = TestClient(
        app, raise_server_exceptions=False, client=("127.0.0.1", 50000)
    ).post(
        "/api/creator/assets",
        content=b"small",
        headers={"content-type": "image/png", "content-length": str(limit + 1)},
    )

    assert response.status_code == 413
    assert response.json()["reason"] == "request_too_large"
    assert response.json()["max_bytes"] == limit
    assert called is False


def test_creator_asset_route_replays_a_valid_bounded_body(monkeypatch):
    png = b"\x89PNG\r\n\x1a\n" + b"asset"
    received = {}

    def capture_add(name, mime, data):
        received.update(name=name, mime=mime, data=data)
        return {"created": True, "asset": {"id": "test-asset"}}

    monkeypatch.setattr(orchestrator.reaction_assets, "add", capture_add)
    response = TestClient(
        app, raise_server_exceptions=False, client=("127.0.0.1", 50000)
    ).post(
        "/api/creator/assets",
        content=png,
        headers={"content-type": "image/png", "x-rareiq-filename": "proof.png"},
    )

    assert response.status_code == 200
    assert response.json()["asset"]["id"] == "test-asset"
    assert received == {"name": "proof.png", "mime": "image/png", "data": png}


def test_multi_card_control_route_rejects_chunked_oversize():
    def chunks():
        yield b'{' + b'"padding":"' + b"x" * (MAX_CONTROL_REQUEST_BYTES // 2)
        yield b"x" * (MAX_CONTROL_REQUEST_BYTES // 2 + 32) + b'"}'

    response = TestClient(
        app, raise_server_exceptions=False, client=("127.0.0.1", 50000)
    ).post(
        "/api/multi-card/select",
        content=chunks(),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json() == {
        "ok": False,
        "reason": "request_too_large",
        "max_bytes": MAX_CONTROL_REQUEST_BYTES,
    }


def test_inventory_receipt_request_has_a_bounded_data_url():
    assert MAX_RECEIPT_DATA_URL_CHARS < 7 * 1024 * 1024
    with pytest.raises(ValidationError):
        InventoryExpenseRequest(amount=1, receipt_data_url="x" * (MAX_RECEIPT_DATA_URL_CHARS + 1))


def test_receipt_rejects_oversized_base64_before_decode(tmp_path, monkeypatch):
    service = InventoryService(tmp_path / "inventory.json")

    def unexpected_decode(*_args, **_kwargs):
        raise AssertionError("oversized receipt reached the decoder")

    monkeypatch.setattr(base64, "b64decode", unexpected_decode)
    result = service.add_expense(
        "supplies",
        1,
        receipt_data_url="data:image/png;base64," + "A" * (MAX_RECEIPT_BASE64_CHARS + 1),
    )

    assert result == {
        "created": False,
        "reason": "receipt_too_large",
        "max_bytes": 5 * 1024 * 1024,
    }


@pytest.mark.parametrize(
    ("data_url", "reason"),
    [
        ("not-a-data-url", "receipt_invalid"),
        ("data:text/html;base64,PGh0bWw+", "receipt_unsupported_media_type"),
        ("data:image/png;base64,%%%", "receipt_invalid"),
        ("data:image/png;base64," + base64.b64encode(b"not-png").decode("ascii"), "receipt_signature_mismatch"),
    ],
)
def test_receipt_rejects_invalid_media_and_content_without_raising(tmp_path, data_url, reason):
    result = InventoryService(tmp_path / "inventory.json").add_expense(
        "supplies", 1, receipt_data_url=data_url
    )

    assert result["created"] is False
    assert result["reason"] == reason


def test_valid_png_receipt_remains_supported(tmp_path):
    service = InventoryService(tmp_path / "inventory.json")
    png = b"\x89PNG\r\n\x1a\n" + b"receipt"
    result = service.add_expense(
        "supplies",
        1,
        receipt_name="receipt.png",
        receipt_data_url="data:image/png;base64," + base64.b64encode(png).decode("ascii"),
    )

    assert result["created"] is True
    receipt = service.expense_receipt(result["expense"]["expense_id"])
    assert receipt is not None
    assert receipt.read_bytes() == png
