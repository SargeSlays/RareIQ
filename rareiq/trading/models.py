from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from math import isfinite
from typing import Any


@dataclass(frozen=True, slots=True)
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("bar timestamp must be timezone-aware")
        prices = (self.open, self.high, self.low, self.close)
        if any(not isfinite(price) for price in (*prices, self.volume)):
            raise ValueError("bar values must be finite")
        if any(price <= 0 for price in prices):
            raise ValueError("OHLC prices must be positive")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("bar high is below another OHLC value")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("bar low is above another OHLC value")
        if self.volume < 0:
            raise ValueError("bar volume cannot be negative")


@dataclass(frozen=True, slots=True)
class ModelSignal:
    as_of: datetime
    probability_up: float
    target_fraction: float
    action: str
    training_samples: int
    reasons: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "probability_up": round(self.probability_up, 6),
            "target_fraction": round(self.target_fraction, 6),
            "action": self.action,
            "training_samples": self.training_samples,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class Quote:
    timestamp: datetime
    bid: float
    ask: float
    bid_size: float = 0.0
    ask_size: float = 0.0

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("quote timestamp must be timezone-aware")
        if any(
            not isfinite(value)
            for value in (self.bid, self.ask, self.bid_size, self.ask_size)
        ):
            raise ValueError("quote values must be finite")
        if self.bid <= 0 or self.ask <= 0:
            raise ValueError("quote prices must be positive")
        if self.ask < self.bid:
            raise ValueError("quote ask cannot be below bid")

    @property
    def midpoint(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread_bps(self) -> float:
        return (self.ask - self.bid) / self.midpoint * 10_000.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "bid": self.bid,
            "ask": self.ask,
            "midpoint": round(self.midpoint, 6),
            "spread_bps": round(self.spread_bps, 4),
        }


@dataclass(frozen=True, slots=True)
class OrderPlan:
    symbol: str
    side: str
    notional: float
    quantity: float
    target_value: float
    current_value: float
    client_order_id: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "notional": round(self.notional, 2),
            "quantity": round(self.quantity, 9),
            "target_value": round(self.target_value, 2),
            "current_value": round(self.current_value, 2),
            "client_order_id": self.client_order_id,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class RiskDecision:
    allowed: bool
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "reasons": list(self.reasons)}


@dataclass(slots=True)
class TradingState:
    high_water_mark: float = 0.0
    halted: bool = False
    halt_reason: str = ""
    last_order_date: str = ""
    last_client_order_id: str = ""
    last_buy_date: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "TradingState":
        known = {name for name in cls.__dataclass_fields__}
        unknown = set(value) - known
        if unknown:
            raise ValueError("trading state contains unknown fields")
        high_water = value.get("high_water_mark", 0.0)
        if isinstance(high_water, bool) or not isinstance(high_water, (int, float)):
            raise ValueError("trading high-water mark must be numeric")
        if not isfinite(float(high_water)) or float(high_water) < 0:
            raise ValueError("trading high-water mark must be finite and nonnegative")
        halted = value.get("halted", False)
        if not isinstance(halted, bool):
            raise ValueError("trading halted flag must be boolean")
        halt_reason = value.get("halt_reason", "")
        last_order_date = value.get("last_order_date", "")
        last_client_order_id = value.get("last_client_order_id", "")
        last_buy_date = value.get("last_buy_date", "")
        strings = (halt_reason, last_order_date, last_client_order_id, last_buy_date)
        if any(not isinstance(item, str) for item in strings):
            raise ValueError("trading state text fields must be strings")
        if len(halt_reason) > 128 or len(last_client_order_id) > 64:
            raise ValueError("trading state text field is too long")
        for date_value in (last_order_date, last_buy_date):
            if date_value:
                date.fromisoformat(date_value)
        metadata = value.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError("trading state metadata must be an object")
        return cls(
            high_water_mark=float(high_water),
            halted=halted,
            halt_reason=halt_reason,
            last_order_date=last_order_date,
            last_client_order_id=last_client_order_id,
            last_buy_date=last_buy_date,
            metadata=dict(metadata),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "high_water_mark": round(float(self.high_water_mark), 6),
            "halted": bool(self.halted),
            "halt_reason": str(self.halt_reason),
            "last_order_date": str(self.last_order_date),
            "last_client_order_id": str(self.last_client_order_id),
            "last_buy_date": str(self.last_buy_date),
            "metadata": dict(self.metadata),
        }
