from __future__ import annotations

import json

import httpx
import pytest

from rareiq.trading.broker import (
    PAPER_TRADING_BASE_URL,
    AlpacaCredentials,
    AlpacaPaperClient,
    BrokerError,
)
from rareiq.trading.models import OrderPlan


def test_credentials_repr_never_contains_secret() -> None:
    credentials = AlpacaCredentials("paper-key", "super-secret")

    assert "super-secret" not in repr(credentials)


def test_order_submission_is_hardwired_to_paper_day_limit_order() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        payload = captured["payload"]
        return httpx.Response(
            200,
            json={
                "id": "paper-1",
                "client_order_id": payload["client_order_id"],
                "symbol": payload["symbol"],
                "side": payload["side"],
                "qty": payload["qty"],
                "filled_qty": "0",
                "status": "accepted",
            },
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    client = AlpacaPaperClient(
        AlpacaCredentials("paper-key", "paper-secret"), client=http_client
    )
    plan = OrderPlan(
        symbol="SPY",
        side="buy",
        notional=10,
        quantity=0.02,
        target_value=25,
        current_value=0,
        client_order_id="riq-test",
        reason="test",
    )

    client.submit_marketable_limit_order(plan, limit_price=500.25)

    assert captured["url"] == f"{PAPER_TRADING_BASE_URL}/v2/orders"
    assert captured["payload"] == {
        "symbol": "SPY",
        "qty": "0.02",
        "side": "buy",
        "type": "limit",
        "time_in_force": "day",
        "order_class": "simple",
        "position_intent": "buy_to_open",
        "limit_price": "500.25",
        "extended_hours": False,
        "client_order_id": "riq-test",
    }
    http_client.close()


def test_safety_critical_broker_lists_reject_partially_malformed_results() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json=[{"id": "valid-looking"}, "malformed"])
    )
    http_client = httpx.Client(transport=transport)
    client = AlpacaPaperClient(
        AlpacaCredentials("paper-key", "paper-secret"), client=http_client
    )

    with pytest.raises(BrokerError, match="positions"):
        client.get_positions()
    with pytest.raises(BrokerError, match="orders"):
        client.get_open_orders()
    with pytest.raises(BrokerError, match="cancel-all"):
        client.cancel_all_orders()

    http_client.close()
