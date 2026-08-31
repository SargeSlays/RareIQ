from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

from rareiq.trading.data import parse_timestamp, validate_bars
from rareiq.trading.models import Bar, OrderPlan, Quote


PAPER_TRADING_BASE_URL = "https://paper-api.alpaca.markets"
MARKET_DATA_BASE_URL = "https://data.alpaca.markets"


class BrokerError(RuntimeError):
    pass


def paper_order_payload(plan: OrderPlan, *, limit_price: float) -> dict[str, Any]:
    if plan.side not in {"buy", "sell"}:
        raise BrokerError("unsupported order side")
    if plan.quantity <= 0 or limit_price <= 0:
        raise BrokerError("order quantity and limit price must be positive")
    return {
        "symbol": plan.symbol,
        "qty": f"{plan.quantity:.9f}".rstrip("0").rstrip("."),
        "side": plan.side,
        "type": "limit",
        "time_in_force": "day",
        "order_class": "simple",
        "position_intent": "buy_to_open" if plan.side == "buy" else "sell_to_close",
        "limit_price": f"{limit_price:.2f}",
        "extended_hours": False,
        "client_order_id": plan.client_order_id,
    }


@dataclass(frozen=True, slots=True)
class AlpacaCredentials:
    key_id: str
    secret_key: str = field(repr=False)

    @classmethod
    def from_environment(cls) -> "AlpacaCredentials":
        key_id = os.getenv("APCA_API_KEY_ID") or os.getenv("ALPACA_API_KEY") or ""
        secret = (
            os.getenv("APCA_API_SECRET_KEY")
            or os.getenv("ALPACA_SECRET_KEY")
            or ""
        )
        if not key_id or not secret:
            raise BrokerError(
                "missing Alpaca paper credentials; set APCA_API_KEY_ID and "
                "APCA_API_SECRET_KEY"
            )
        return cls(key_id=key_id, secret_key=secret)


class AlpacaPaperClient:
    """Minimal direct REST adapter whose trading host is permanently paper-only."""

    def __init__(
        self,
        credentials: AlpacaCredentials,
        *,
        timeout_seconds: float = 15.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._headers = {
            "APCA-API-KEY-ID": credentials.key_id,
            "APCA-API-SECRET-KEY": credentials.secret_key,
            "Accept": "application/json",
        }
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "AlpacaPaperClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        allow_not_found: bool = False,
    ) -> Any:
        try:
            response = self._client.request(
                method, url, headers=self._headers, params=params, json=json
            )
        except httpx.HTTPError as exc:
            raise BrokerError(f"broker request failed: {type(exc).__name__}") from exc
        if allow_not_found and response.status_code == 404:
            return None
        if response.is_error:
            detail = response.text.replace("\n", " ")[:300]
            raise BrokerError(f"broker returned HTTP {response.status_code}: {detail}")
        try:
            return response.json()
        except ValueError as exc:
            raise BrokerError("broker returned invalid JSON") from exc

    def get_account(self) -> dict[str, Any]:
        result = self._request("GET", f"{PAPER_TRADING_BASE_URL}/v2/account")
        if not isinstance(result, dict):
            raise BrokerError("invalid account response")
        return result

    def get_clock(self) -> dict[str, Any]:
        result = self._request("GET", f"{PAPER_TRADING_BASE_URL}/v2/clock")
        if not isinstance(result, dict) or "timestamp" not in result:
            raise BrokerError("invalid market clock response")
        return result

    def get_positions(self) -> list[dict[str, Any]]:
        result = self._request("GET", f"{PAPER_TRADING_BASE_URL}/v2/positions")
        if not isinstance(result, list) or any(not isinstance(item, dict) for item in result):
            raise BrokerError("invalid positions response")
        return result

    def get_asset(self, symbol: str) -> dict[str, Any]:
        result = self._request(
            "GET", f"{PAPER_TRADING_BASE_URL}/v2/assets/{symbol}"
        )
        if not isinstance(result, dict):
            raise BrokerError("invalid asset response")
        return result

    def get_open_orders(self) -> list[dict[str, Any]]:
        result = self._request(
            "GET",
            f"{PAPER_TRADING_BASE_URL}/v2/orders",
            params={"status": "open", "limit": 100, "direction": "desc"},
        )
        if not isinstance(result, list) or any(not isinstance(item, dict) for item in result):
            raise BrokerError("invalid orders response")
        return result

    def get_order_by_client_id(self, client_order_id: str) -> dict[str, Any] | None:
        result = self._request(
            "GET",
            f"{PAPER_TRADING_BASE_URL}/v2/orders:by_client_order_id",
            params={"client_order_id": client_order_id},
            allow_not_found=True,
        )
        if result is None:
            return None
        if not isinstance(result, dict):
            raise BrokerError("invalid order lookup response")
        return result

    def cancel_all_orders(self) -> list[dict[str, Any]]:
        result = self._request("DELETE", f"{PAPER_TRADING_BASE_URL}/v2/orders")
        if not isinstance(result, list) or any(not isinstance(item, dict) for item in result):
            raise BrokerError("invalid cancel-all response")
        if any(
            item.get("id") in (None, "") or item.get("status") in (None, "")
            for item in result
        ):
            raise BrokerError("cancel-all response is missing order identity fields")
        return result

    def get_latest_quote(self, symbol: str, *, feed: str = "iex") -> Quote:
        result = self._request(
            "GET",
            f"{MARKET_DATA_BASE_URL}/v2/stocks/{symbol}/quotes/latest",
            params={"feed": feed},
        )
        quote = result.get("quote") if isinstance(result, dict) else None
        if not isinstance(quote, dict):
            raise BrokerError("invalid latest-quote response")
        try:
            return Quote(
                timestamp=parse_timestamp(str(quote["t"])),
                bid=float(quote["bp"]),
                ask=float(quote["ap"]),
                bid_size=float(quote.get("bs") or 0),
                ask_size=float(quote.get("as") or 0),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BrokerError("latest IEX quote is missing valid bid/ask fields") from exc

    def get_daily_bars(
        self,
        symbol: str,
        *,
        start: datetime,
        end: datetime,
        feed: str = "iex",
    ) -> list[Bar]:
        params: dict[str, Any] = {
            "timeframe": "1Day",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "limit": 10_000,
            "adjustment": "all",
            "feed": feed,
            "sort": "asc",
        }
        bars: list[Bar] = []
        while True:
            result = self._request(
                "GET",
                f"{MARKET_DATA_BASE_URL}/v2/stocks/{symbol}/bars",
                params=params,
            )
            rows = result.get("bars") if isinstance(result, dict) else None
            if not isinstance(rows, list):
                raise BrokerError("invalid historical-bars response")
            try:
                bars.extend(
                    Bar(
                        timestamp=parse_timestamp(str(row["t"])),
                        open=float(row["o"]),
                        high=float(row["h"]),
                        low=float(row["l"]),
                        close=float(row["c"]),
                        volume=float(row.get("v") or 0),
                    )
                    for row in rows
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise BrokerError("historical bars contain invalid OHLCV data") from exc
            token = result.get("next_page_token") if isinstance(result, dict) else None
            if not token:
                break
            params["page_token"] = token
        try:
            return validate_bars(bars)
        except ValueError as exc:
            raise BrokerError(str(exc)) from exc

    def submit_marketable_limit_order(
        self, plan: OrderPlan, *, limit_price: float
    ) -> dict[str, Any]:
        payload = paper_order_payload(plan, limit_price=limit_price)
        result = self._request(
            "POST", f"{PAPER_TRADING_BASE_URL}/v2/orders", json=payload
        )
        if not isinstance(result, dict) or not result.get("id"):
            raise BrokerError("invalid order-submission response")
        return result
