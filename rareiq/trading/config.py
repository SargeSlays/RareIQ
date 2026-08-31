from __future__ import annotations

import json
import math
from numbers import Real
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class TradingConfigError(ValueError):
    """Raised when a setting would weaken the paper-first safety envelope."""


@dataclass(frozen=True, slots=True)
class TradingConfig:
    mode: str = "research"
    strategy: str = "sma_regime"
    symbol: str = "SPY"
    allowed_symbols: tuple[str, ...] = ("SPY",)
    starting_cash: float = 100.0
    managed_equity_ceiling: float = 125.0
    max_position_fraction: float = 0.25
    rebalance_drift_fraction: float = 0.02
    max_order_fraction: float = 0.10
    cash_buffer_fraction: float = 0.10
    daily_loss_limit_fraction: float = 0.01
    max_drawdown_fraction: float = 0.08
    entry_probability: float = 0.58
    exit_probability: float = 0.48
    prediction_horizon_bars: int = 5
    minimum_training_samples: int = 160
    training_window_bars: int = 756
    retrain_every_bars: int = 1
    return_hurdle_bps: float = 20.0
    slippage_bps: float = 10.0
    fee_bps: float = 0.5
    history_calendar_days: int = 2200
    data_feed: str = "iex"
    runtime_directory: str = "runtime/trading"

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str)
            for value in (self.mode, self.strategy, self.symbol, self.data_feed)
        ):
            raise TradingConfigError("mode, strategy, symbol, and data_feed must be strings")
        if not isinstance(self.runtime_directory, (str, Path)):
            raise TradingConfigError("runtime_directory must be a path string")
        if not isinstance(self.allowed_symbols, (tuple, list)) or isinstance(
            self.allowed_symbols, (str, bytes)
        ):
            raise TradingConfigError("allowed_symbols must be a list of ticker strings")
        if any(not isinstance(item, str) for item in self.allowed_symbols):
            raise TradingConfigError("allowed_symbols must contain strings")
        mode = self.mode.strip().lower()
        strategy = self.strategy.strip().lower()
        symbol = self.symbol.strip().upper()
        allowed = tuple(str(item).strip().upper() for item in self.allowed_symbols)
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "strategy", strategy)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "allowed_symbols", allowed)
        runtime_path = Path(self.runtime_directory)
        if not runtime_path.is_absolute():
            runtime_path = PROJECT_ROOT / runtime_path
        runtime_path = runtime_path.resolve()
        object.__setattr__(self, "runtime_directory", str(runtime_path))

        numeric_fields = (
            "starting_cash",
            "managed_equity_ceiling",
            "max_position_fraction",
            "rebalance_drift_fraction",
            "max_order_fraction",
            "cash_buffer_fraction",
            "daily_loss_limit_fraction",
            "max_drawdown_fraction",
            "entry_probability",
            "exit_probability",
            "return_hurdle_bps",
            "slippage_bps",
            "fee_bps",
        )
        if any(
            isinstance(getattr(self, name), bool)
            or not isinstance(getattr(self, name), Real)
            for name in numeric_fields
        ):
            raise TradingConfigError("numeric configuration values must be numbers")
        if any(not math.isfinite(float(getattr(self, name))) for name in numeric_fields):
            raise TradingConfigError("numeric configuration values must be finite")
        integer_fields = (
            "prediction_horizon_bars",
            "minimum_training_samples",
            "training_window_bars",
            "retrain_every_bars",
            "history_calendar_days",
        )
        if any(
            isinstance(getattr(self, name), bool)
            or not isinstance(getattr(self, name), int)
            for name in integer_fields
        ):
            raise TradingConfigError("bar-count configuration values must be integers")

        if mode not in {"research", "paper"}:
            raise TradingConfigError(
                "mode must be 'research' or 'paper'; live trading is intentionally unavailable"
            )
        if strategy not in {"sma_regime", "walk_forward_logistic"}:
            raise TradingConfigError(
                "strategy must be 'sma_regime' or 'walk_forward_logistic'"
            )
        if not allowed or symbol not in allowed:
            raise TradingConfigError("symbol must appear in allowed_symbols")
        if symbol != "SPY" or allowed != ("SPY",):
            raise TradingConfigError("phase one is pinned to SPY only")
        if float(self.starting_cash) != 100.0:
            raise TradingConfigError("phase one requires starting_cash=100 exactly")
        if self.managed_equity_ceiling < self.starting_cash:
            raise TradingConfigError("managed_equity_ceiling cannot be below starting_cash")
        if self.managed_equity_ceiling > 250:
            raise TradingConfigError("phase-one managed_equity_ceiling cannot exceed $250")
        if not 0 < self.max_position_fraction <= 0.35:
            raise TradingConfigError("max_position_fraction must be in (0, 0.35]")
        if not 0 <= self.rebalance_drift_fraction <= 0.05:
            raise TradingConfigError("rebalance_drift_fraction must be in [0, 0.05]")
        if not 0 < self.max_order_fraction <= 0.10:
            raise TradingConfigError("max_order_fraction must be in (0, 0.10]")
        if not 0.05 <= self.cash_buffer_fraction < 1:
            raise TradingConfigError("cash_buffer_fraction must be at least 0.05")
        if self.max_position_fraction + self.cash_buffer_fraction > 1:
            raise TradingConfigError("position and cash-buffer fractions cannot exceed 1")
        if not 0 < self.daily_loss_limit_fraction <= 0.02:
            raise TradingConfigError("daily_loss_limit_fraction must be in (0, 0.02]")
        if not 0 < self.max_drawdown_fraction <= 0.10:
            raise TradingConfigError("max_drawdown_fraction must be in (0, 0.10]")
        if not 0.52 <= self.entry_probability <= 0.75:
            raise TradingConfigError("entry_probability must be between 0.52 and 0.75")
        if not 0.25 <= self.exit_probability < self.entry_probability:
            raise TradingConfigError("exit_probability must be below entry_probability")
        if not 1 <= self.prediction_horizon_bars <= 20:
            raise TradingConfigError("prediction_horizon_bars must be between 1 and 20")
        if self.minimum_training_samples < 100:
            raise TradingConfigError("minimum_training_samples must be at least 100")
        if self.training_window_bars < self.minimum_training_samples:
            raise TradingConfigError("training_window_bars is smaller than the minimum sample count")
        if not 1 <= self.retrain_every_bars <= 20:
            raise TradingConfigError("retrain_every_bars must be between 1 and 20")
        if (
            mode == "paper"
            and strategy == "walk_forward_logistic"
            and self.retrain_every_bars != 1
        ):
            raise TradingConfigError(
                "paper logistic runs require retrain_every_bars=1 for backtest parity"
            )
        if not 0 <= self.return_hurdle_bps <= 100:
            raise TradingConfigError("return_hurdle_bps must be between 0 and 100")
        if not 0 <= self.slippage_bps <= 50:
            raise TradingConfigError("slippage_bps must be between 0 and 50")
        if not 0 <= self.fee_bps <= 20:
            raise TradingConfigError("fee_bps must be between 0 and 20")
        if self.history_calendar_days < 500:
            raise TradingConfigError("history_calendar_days must be at least 500")
        if self.data_feed != "iex":
            raise TradingConfigError("phase one uses the free IEX feed only")
        canonical_runtime = (PROJECT_ROOT / "runtime" / "trading").resolve()
        if runtime_path != canonical_runtime:
            raise TradingConfigError(
                "phase one requires the canonical runtime/trading state directory"
            )

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "TradingConfig":
        known = {item.name for item in fields(cls)}
        unknown = sorted(set(value) - known)
        if unknown:
            raise TradingConfigError(f"unknown configuration keys: {', '.join(unknown)}")
        normalized = dict(value)
        if "allowed_symbols" in normalized:
            if not isinstance(normalized["allowed_symbols"], (list, tuple)):
                raise TradingConfigError("allowed_symbols must be a JSON array")
            normalized["allowed_symbols"] = tuple(normalized["allowed_symbols"])
        return cls(**normalized)

    @classmethod
    def load(cls, path: str | Path) -> "TradingConfig":
        config_path = Path(path)
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise TradingConfigError(f"configuration file not found: {config_path}") from exc
        except json.JSONDecodeError as exc:
            raise TradingConfigError(f"invalid JSON in {config_path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise TradingConfigError("configuration root must be a JSON object")
        return cls.from_mapping(payload)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_symbols"] = list(self.allowed_symbols)
        return payload
