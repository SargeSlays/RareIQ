from __future__ import annotations

import hashlib
import json
import os
import re
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path
from typing import Any
from math import isfinite

from rareiq.trading.config import TradingConfig
from rareiq.trading.models import ModelSignal, OrderPlan, Quote, RiskDecision, TradingState


MAX_QUOTE_AGE_SECONDS = 5.0
MAX_SPREAD_BPS = 20.0
LIMIT_COLLAR_BPS = 5.0
OPENING_EXECUTION_WINDOW_MINUTES = 5


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def marketable_limit_price(quote: Quote, side: str) -> float:
    if side == "buy":
        raw = _decimal(quote.ask) * (Decimal("1") + _decimal(LIMIT_COLLAR_BPS) / 10_000)
        return float(raw.quantize(Decimal("0.01"), rounding=ROUND_CEILING))
    if side == "sell":
        raw = _decimal(quote.bid) * (Decimal("1") - _decimal(LIMIT_COLLAR_BPS) / 10_000)
        return float(raw.quantize(Decimal("0.01"), rounding=ROUND_FLOOR))
    raise ValueError("unsupported order side")


def build_order_plan(
    config: TradingConfig,
    signal: ModelSignal,
    *,
    equity: float,
    position_quantity: float,
    quote: Quote,
    session_date: str,
) -> OrderPlan | None:
    equity_value = _decimal(equity)
    midpoint = _decimal(quote.midpoint)
    current_value = _decimal(position_quantity) * midpoint
    target_fraction = min(signal.target_fraction, config.max_position_fraction)
    target_value = equity_value * _decimal(target_fraction)
    difference = target_value - current_value
    current_fraction = (
        Decimal("0") if equity_value <= 0 else current_value / equity_value
    )
    if (
        target_fraction > 0
        and difference < 0
        and current_fraction
        <= _decimal(min(0.35, target_fraction + config.rebalance_drift_fraction))
    ):
        return None
    if difference >= 0 and difference < Decimal("1.00"):
        return None
    if difference < 0 and abs(difference) < Decimal("0.01"):
        return None

    side = "buy" if difference > 0 else "sell"
    if side == "buy":
        notional = min(difference, equity_value * _decimal(config.max_order_fraction))
    else:
        notional = min(abs(difference), current_value)
    if side == "buy" and notional < Decimal("1.00"):
        return None
    if side == "sell" and notional < Decimal("0.01"):
        return None
    limit_price = _decimal(marketable_limit_price(quote, side))
    quantity = notional / limit_price
    if side == "sell":
        quantity = min(quantity, _decimal(position_quantity))
        notional = quantity * limit_price

    identity = "|".join(
        (
            "riq-paper-v1",
            config.strategy,
            signal.as_of.isoformat(),
            config.symbol,
            f"{target_fraction:.6f}",
            side,
            session_date,
        )
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    client_order_id = f"riq-{session_date.replace('-', '')}-{side[0]}-{digest}"
    return OrderPlan(
        symbol=config.symbol,
        side=side,
        notional=float(notional),
        quantity=float(quantity),
        target_value=float(target_value),
        current_value=float(current_value),
        client_order_id=client_order_id,
        reason=signal.action,
    )


def update_halt_state(
    config: TradingConfig, state: TradingState, account: dict[str, Any]
) -> None:
    try:
        equity = float(account["equity"])
        last_equity = float(account["last_equity"])
    except (KeyError, TypeError, ValueError):
        state.halted = True
        state.halt_reason = "invalid_account_balance_halt"
        return
    if (
        not isfinite(equity)
        or not isfinite(last_equity)
        or equity <= 0
        or last_equity <= 0
    ):
        state.halted = True
        state.halt_reason = "invalid_account_balance_halt"
        return
    state.high_water_mark = max(float(state.high_water_mark), equity)
    if state.halted:
        if not state.halt_reason:
            state.halt_reason = "risk_engine_halted"
        return
    if equity > config.managed_equity_ceiling + 0.01:
        state.halted = True
        state.halt_reason = "managed_equity_review_halt"
        return
    drawdown = (
        0.0 if state.high_water_mark <= 0 else 1.0 - equity / state.high_water_mark
    )
    daily_loss = 0.0 if last_equity <= 0 else 1.0 - equity / last_equity
    if drawdown >= config.max_drawdown_fraction:
        state.halted = True
        state.halt_reason = "max_drawdown_halt"
    elif daily_loss >= config.daily_loss_limit_fraction:
        state.halted = True
        state.halt_reason = "daily_loss_halt"


def evaluate_risk(
    config: TradingConfig,
    state: TradingState,
    plan: OrderPlan,
    *,
    account: dict[str, Any],
    quote: Quote,
    clock: dict[str, Any],
    position_quantity: float,
    require_open_market: bool,
) -> RiskDecision:
    reasons = list(
        evaluate_preflight(
            config,
            state,
            account=account,
            quote=quote,
            clock=clock,
            require_open_market=require_open_market,
        )
    )
    try:
        equity = float(account["equity"])
        cash = float(account["cash"])
    except (KeyError, TypeError, ValueError):
        equity = float("nan")
        cash = float("nan")
    try:
        session_timestamp = datetime.fromisoformat(
            str(clock["timestamp"]).replace("Z", "+00:00")
        )
        if session_timestamp.tzinfo is None:
            raise ValueError
        session_date = session_timestamp.date().isoformat()
    except (KeyError, TypeError, ValueError):
        session_date = ""
    if plan.symbol not in config.allowed_symbols:
        reasons.append("symbol_not_allowed")
    reducing_risk = plan.side == "sell"
    if reducing_risk:
        reasons = [
            reason
            for reason in reasons
            if reason
            not in {
                "managed_equity_ceiling_exceeded",
                "negative_cash_balance",
                "outside_opening_execution_window",
                "market_open_time_unavailable",
            }
        ]
    if state.last_order_date == session_date and not reducing_risk:
        reasons.append("daily_order_limit_reached")
    if (
        reducing_risk
        and state.last_buy_date == session_date
        and not state.halted
    ):
        reasons.append("routine_same_day_round_trip_blocked")

    if state.halted and not reducing_risk:
        reasons.append(state.halt_reason or "risk_engine_halted")

    if plan.side == "buy":
        max_order = equity * config.max_order_fraction
        if plan.notional > max_order + 0.02:
            reasons.append("order_notional_exceeds_limit")
        projected_value = position_quantity * quote.midpoint + plan.notional
        if projected_value > equity * config.max_position_fraction + 0.02:
            reasons.append("projected_position_exceeds_limit")
        if cash - plan.notional < equity * config.cash_buffer_fraction - 0.02:
            reasons.append("cash_buffer_would_be_breached")
    elif plan.side == "sell":
        if plan.quantity > position_quantity + 1e-8:
            reasons.append("sell_quantity_exceeds_position")
    else:
        reasons.append("unsupported_order_side")

    if plan.side == "buy" and plan.notional < 1.0:
        reasons.append("order_below_one_dollar_minimum")
    return RiskDecision(allowed=not reasons, reasons=tuple(reasons))


def evaluate_preflight(
    config: TradingConfig,
    state: TradingState,
    *,
    account: dict[str, Any],
    quote: Quote,
    clock: dict[str, Any],
    require_open_market: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    try:
        equity = float(account["equity"])
        cash = float(account["cash"])
    except (KeyError, TypeError, ValueError):
        equity = float("nan")
        cash = float("nan")
    status_value = account.get("status")
    status = status_value.upper() if isinstance(status_value, str) else ""
    try:
        session_timestamp = datetime.fromisoformat(
            str(clock["timestamp"]).replace("Z", "+00:00")
        )
        if session_timestamp.tzinfo is None:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        session_timestamp = None
        reasons.append("market_clock_timestamp_invalid")
    quote_timestamp = quote.timestamp
    quote_age = (
        None
        if session_timestamp is None
        else (
            session_timestamp.astimezone(timezone.utc)
            - quote_timestamp.astimezone(timezone.utc)
        ).total_seconds()
    )

    if config.mode != "paper":
        reasons.append("configuration_not_in_paper_mode")
    if status != "ACTIVE":
        reasons.append("broker_account_not_active")
    block_fields = (
        "trading_blocked",
        "account_blocked",
        "trade_suspended_by_user",
    )
    if any(not isinstance(account.get(name), bool) for name in block_fields):
        reasons.append("broker_account_block_flags_unavailable")
    elif any(account[name] for name in block_fields):
        reasons.append("broker_account_is_blocked")
    if not isfinite(equity) or not isfinite(cash) or equity <= 0:
        reasons.append("invalid_account_balance")
    if isfinite(cash) and cash < 0:
        reasons.append("negative_cash_balance")
    if equity > config.managed_equity_ceiling + 0.01:
        reasons.append("managed_equity_ceiling_exceeded")
    clock_open = clock.get("is_open")
    if not isinstance(clock_open, bool):
        reasons.append("market_clock_open_flag_invalid")
    elif require_open_market and not clock_open:
        reasons.append("regular_market_is_closed")
    if require_open_market and clock_open is True and session_timestamp is not None:
        next_close_raw = clock.get("next_close")
        try:
            next_close = datetime.fromisoformat(
                str(next_close_raw).replace("Z", "+00:00")
            )
            if next_close.tzinfo is None:
                raise ValueError
            local_timestamp = session_timestamp.astimezone(next_close.tzinfo)
            session_open = local_timestamp.replace(
                hour=9, minute=30, second=0, microsecond=0
            )
            window_end = session_open + timedelta(
                minutes=OPENING_EXECUTION_WINDOW_MINUTES
            )
            if not session_open <= local_timestamp < window_end:
                reasons.append("outside_opening_execution_window")
        except (TypeError, ValueError):
            reasons.append("market_open_time_unavailable")
    if quote_age is None or quote_age < -1 or quote_age > MAX_QUOTE_AGE_SECONDS:
        reasons.append("quote_is_stale")
    if quote.spread_bps > MAX_SPREAD_BPS:
        reasons.append("quoted_spread_too_wide")
    update_halt_state(config, state, account)
    return tuple(reasons)


class TradingStateStore:
    def __init__(self, runtime_directory: str | Path) -> None:
        self.directory = Path(runtime_directory)
        self.state_path = self.directory / "state.json"
        self.journal_path = self.directory / "journal.jsonl"
        self.binding_path = self.directory / "account_binding.json"
        self.kill_switch_path = self.directory / "KILL_SWITCH.json"

    def load(self) -> TradingState:
        return self._load_unlocked()

    def _load_unlocked(self) -> TradingState:
        if not self.state_path.exists():
            state = TradingState()
        else:
            try:
                value = json.loads(
                    self.state_path.read_text(encoding="utf-8"),
                    parse_constant=lambda item: (_ for _ in ()).throw(
                        ValueError(f"invalid JSON constant: {item}")
                    ),
                )
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                raise RuntimeError(
                    "trading state is unreadable; refusing to continue"
                ) from exc
            if not isinstance(value, dict):
                raise RuntimeError("trading state root is invalid; refusing to continue")
            try:
                state = TradingState.from_mapping(value)
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    "trading state schema is invalid; refusing to continue"
                ) from exc
        if self.kill_switch_latched():
            state.halted = True
            state.halt_reason = "manual_kill_switch"
        return state

    def kill_switch_latched(self) -> bool:
        return self.kill_switch_path.is_file()

    def latch_kill_switch(self) -> None:
        with self._exclusive_lock("kill-switch.lock"):
            if self.kill_switch_path.exists():
                return
            temporary = self.kill_switch_path.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "reason": "manual_kill_switch",
                        "latched_at": datetime.now(timezone.utc).isoformat(),
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.kill_switch_path)

    def _load_binding_unlocked(self) -> dict[str, Any] | None:
        if not self.binding_path.exists():
            return None
        try:
            value = json.loads(self.binding_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("paper account binding is unreadable") from exc
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "broker_account_id",
            "paper_config_sha256",
            "initial_equity",
        }:
            raise RuntimeError("paper account binding schema is invalid")
        account_id = value.get("broker_account_id")
        config_digest = value.get("paper_config_sha256")
        initial_equity = value.get("initial_equity")
        if (
            value.get("schema_version") != 1
            or isinstance(value.get("schema_version"), bool)
            or not isinstance(account_id, str)
            or not account_id.strip()
            or not isinstance(config_digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", config_digest) is None
            or isinstance(initial_equity, bool)
            or not isinstance(initial_equity, (int, float))
            or not isfinite(float(initial_equity))
            or abs(float(initial_equity) - 100.0) > 0.01
        ):
            raise RuntimeError("paper account binding schema is invalid")
        return dict(value)

    def load_binding(self) -> dict[str, Any] | None:
        with self._exclusive_lock("binding.lock"):
            return self._load_binding_unlocked()

    def bind_account(
        self, *, broker_account_id: str, paper_config_sha256: str, initial_equity: float
    ) -> dict[str, Any]:
        requested = {
            "schema_version": 1,
            "broker_account_id": broker_account_id,
            "paper_config_sha256": paper_config_sha256,
            "initial_equity": round(float(initial_equity), 2),
        }
        with self._exclusive_lock("binding.lock"):
            existing = self._load_binding_unlocked()
            if existing is not None:
                if existing != requested:
                    raise RuntimeError(
                        "paper account binding differs from the requested account/configuration"
                    )
                return existing
            temporary = self.binding_path.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(requested, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.binding_path)
            return requested

    @contextmanager
    def _exclusive_lock(
        self, name: str = "state.lock", *, wait_seconds: float = 5.0
    ):
        self.directory.mkdir(parents=True, exist_ok=True)
        lock_path = self.directory / name
        handle = lock_path.open("a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        acquired = False
        try:
            if os.name == "nt":
                import msvcrt

                attempts = max(1, int(wait_seconds / 0.05))
                for _ in range(attempts):
                    try:
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        acquired = True
                        break
                    except OSError:
                        time.sleep(0.05)
                if not acquired:
                    raise RuntimeError("timed out acquiring the trading-state lock")
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                acquired = True
            yield
        finally:
            if acquired:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    @contextmanager
    def execution_guard(self, *, wait_seconds: float = 5.0):
        with self._exclusive_lock("execution.lock", wait_seconds=wait_seconds):
            yield

    def save(self, state: TradingState) -> None:
        with self._exclusive_lock():
            existing = self._load_unlocked()
            if self.kill_switch_latched():
                state.halted = True
                state.halt_reason = "manual_kill_switch"
            state.high_water_mark = max(state.high_water_mark, existing.high_water_mark)
            if existing.halted:
                state.halted = True
                state.halt_reason = existing.halt_reason or state.halt_reason
            if existing.last_order_date > state.last_order_date:
                state.last_order_date = existing.last_order_date
                state.last_client_order_id = existing.last_client_order_id
            if existing.last_buy_date > state.last_buy_date:
                state.last_buy_date = existing.last_buy_date
            state.metadata = {**existing.metadata, **state.metadata}
            temporary = self.state_path.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(
                    state.as_dict(), indent=2, sort_keys=True, allow_nan=False
                )
                + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.state_path)

    def append_event(self, event: dict[str, Any]) -> None:
        with self._exclusive_lock("journal.lock"):
            record = {
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                **event,
            }
            with self.journal_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        record,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    )
                    + "\n"
                )
                handle.flush()
                os.fsync(handle.fileno())
