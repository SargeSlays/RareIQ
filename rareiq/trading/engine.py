from __future__ import annotations

import hashlib
import json
import math
import os
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from rareiq.trading.broker import AlpacaPaperClient, BrokerError, paper_order_payload
from rareiq.trading.config import TradingConfig
from rareiq.trading.models import Bar, ModelSignal, OrderPlan, Quote, TradingState
from rareiq.trading.risk import (
    TradingStateStore,
    build_order_plan,
    evaluate_preflight,
    evaluate_risk,
    marketable_limit_price,
    update_halt_state,
)
from rareiq.trading.strategy import build_strategy


PAPER_ACKNOWLEDGEMENT = "PAPER_ONLY_I_ACCEPT_SIMULATED_ORDERS"
ORDER_TRANSMISSION_MARGIN_SECONDS = 2.0
COMMITTED_ORDER_STATUSES = {
    "accepted",
    "pending_review",
    "pending_new",
    "new",
    "partially_filled",
    "accepted_for_bidding",
    "stopped",
    "filled",
    "done_for_day",
    "calculated",
}
TERMINAL_ORDER_STATUSES = {"canceled", "expired", "rejected", "suspended"}
MANUAL_ORDER_STATUSES = {"replaced", "pending_replace", "pending_cancel", "held"}


def _clock_time(clock: dict[str, Any]) -> datetime:
    try:
        value = datetime.fromisoformat(str(clock["timestamp"]).replace("Z", "+00:00"))
    except (KeyError, ValueError) as exc:
        raise BrokerError("invalid market clock timestamp") from exc
    if value.tzinfo is None:
        raise BrokerError("market clock timestamp must be timezone-aware")
    if not isinstance(clock.get("is_open"), bool):
        raise BrokerError("market clock is_open flag must be boolean")
    if clock["is_open"]:
        try:
            next_close = datetime.fromisoformat(
                str(clock["next_close"]).replace("Z", "+00:00")
            )
        except (KeyError, ValueError) as exc:
            raise BrokerError("invalid market next_close timestamp") from exc
        if next_close.tzinfo is None:
            raise BrokerError("market next_close timestamp must be timezone-aware")
    return value


class PaperTradingEngine:
    def __init__(
        self,
        config: TradingConfig,
        client: AlpacaPaperClient,
        state_store: TradingStateStore | None = None,
    ) -> None:
        self.config = config
        self.client = client
        self.state_store = state_store or TradingStateStore(config.runtime_directory)
        if self.state_store.directory.resolve() != Path(config.runtime_directory).resolve():
            raise ValueError("state store must use the configuration's canonical directory")

    def _config_digest(self) -> str:
        payload = json.dumps(
            self.config.as_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _validate_account_schema(account: dict[str, Any]) -> None:
        if not isinstance(account.get("id"), str) or not str(account["id"]).strip():
            raise BrokerError("broker account response is missing its account ID")
        if not isinstance(account.get("status"), str) or not str(
            account["status"]
        ).strip():
            raise BrokerError("broker account response is missing its status")
        for name in ("equity", "cash", "last_equity"):
            if name not in account:
                raise BrokerError(f"broker account response is missing {name}")
            try:
                value = float(account[name])
            except (TypeError, ValueError) as exc:
                raise BrokerError(f"broker account has an invalid {name}") from exc
            if not math.isfinite(value):
                raise BrokerError(f"broker account has a non-finite {name}")
            if name != "cash" and value <= 0:
                raise BrokerError(f"broker account has a non-positive {name}")
        for name in (
            "trading_blocked",
            "account_blocked",
            "trade_suspended_by_user",
        ):
            if not isinstance(account.get(name), bool):
                raise BrokerError(
                    f"broker account response requires a boolean {name} flag"
                )

    def _position_quantity(self, positions: list[dict[str, Any]]) -> float:
        configured_quantity = 0.0
        for item in positions:
            symbol_value = item.get("symbol")
            if not isinstance(symbol_value, str) or not symbol_value.strip():
                raise BrokerError("broker position is missing a valid symbol")
            symbol = symbol_value.strip().upper()
            if item.get("qty") in (None, ""):
                raise BrokerError("broker position is missing its quantity")
            side_value = item.get("side")
            if not isinstance(side_value, str) or side_value.lower() not in {
                "long",
                "short",
            }:
                raise BrokerError("broker position is missing a valid side")
            try:
                quantity = float(item["qty"])
            except (TypeError, ValueError) as exc:
                raise BrokerError("broker position has an invalid quantity") from exc
            if not math.isfinite(quantity):
                raise BrokerError("broker position has a non-finite quantity")
            if side_value.lower() == "short" and abs(quantity) > 1e-9:
                raise BrokerError(
                    "short positions are unsupported and require manual reconciliation"
                )
            if symbol != self.config.symbol and abs(quantity) > 1e-9:
                raise BrokerError(
                    f"unexpected broker position requires manual reconciliation: {symbol}"
                )
            if symbol == self.config.symbol:
                configured_quantity += quantity
        if configured_quantity < -1e-9:
            raise BrokerError("short positions are unsupported and require manual reconciliation")
        return max(0.0, configured_quantity)

    def _snapshot(
        self,
    ) -> tuple[dict[str, Any], float, Quote, dict[str, Any], datetime]:
        account = self.client.get_account()
        position_quantity = self._position_quantity(self.client.get_positions())
        quote = self.client.get_latest_quote(
            self.config.symbol, feed=self.config.data_feed
        )
        clock = self.client.get_clock()
        clock_time = _clock_time(clock)
        self._validate_account_schema(account)
        return account, position_quantity, quote, clock, clock_time

    def _bind_account(
        self,
        state: TradingState,
        account: dict[str, Any],
        position_quantity: float,
    ) -> None:
        account_id = str(account.get("id") or "").strip()
        if not account_id:
            raise BrokerError("broker account response is missing its account ID")
        binding = self.state_store.load_binding()
        state_bound_id = str(state.metadata.get("broker_account_id") or "")
        binding_bound_id = str((binding or {}).get("broker_account_id") or "")
        if state_bound_id and binding_bound_id and state_bound_id != binding_bound_id:
            raise BrokerError("local state and immutable broker binding disagree")
        bound_id = binding_bound_id or state_bound_id
        if bound_id and bound_id != account_id:
            raise BrokerError("local trading state belongs to a different broker account")
        config_digest = self._config_digest()
        state_digest = str(state.metadata.get("paper_config_sha256") or "")
        binding_digest = str((binding or {}).get("paper_config_sha256") or "")
        if state_digest and binding_digest and state_digest != binding_digest:
            raise BrokerError("local state and immutable configuration binding disagree")
        bound_digest = binding_digest or state_digest
        if bound_digest and bound_digest != config_digest:
            raise BrokerError(
                "paper configuration changed after account binding; review and reset state manually"
            )
        if not bound_id:
            equity = float(account.get("equity") or 0)
            cash = float(account.get("cash") or 0)
            if abs(position_quantity) > 1e-9:
                raise BrokerError(
                    "first-run paper account must be flat before local state can be initialized"
                )
            if (
                abs(equity - self.config.starting_cash) > 0.01
                or abs(cash - self.config.starting_cash) > 0.01
            ):
                raise BrokerError(
                    "first-run paper account equity and cash must match starting_cash within one cent"
                )
            binding = self.state_store.bind_account(
                broker_account_id=account_id,
                paper_config_sha256=config_digest,
                initial_equity=equity,
            )
        elif binding is None:
            initial_equity = float(state.metadata.get("initial_equity") or 0)
            if abs(initial_equity - 100.0) > 0.01:
                raise BrokerError(
                    "legacy state cannot be migrated without an exact $100 initial equity"
                )
            binding = self.state_store.bind_account(
                broker_account_id=account_id,
                paper_config_sha256=config_digest,
                initial_equity=initial_equity,
            )
        state.metadata["broker_account_id"] = str(binding["broker_account_id"])
        state.metadata["paper_config_sha256"] = str(binding["paper_config_sha256"])
        state.metadata["initial_equity"] = float(binding["initial_equity"])

    def _signal(
        self,
        bars: list[Bar],
        state: TradingState,
        *,
        equity: float,
        position_quantity: float,
        quote: Quote,
    ) -> ModelSignal:
        current_fraction = (
            0.0 if equity <= 0 else position_quantity * quote.midpoint / equity
        )
        signal = build_strategy(self.config).signal(bars, current_fraction)
        if not state.halted:
            return signal
        return ModelSignal(
            as_of=signal.as_of,
            probability_up=signal.probability_up,
            target_fraction=0.0,
            action="risk_exit",
            training_samples=signal.training_samples,
            reasons=(*signal.reasons, state.halt_reason or "risk_engine_halted"),
        )

    def _refresh_signal_target(
        self,
        candidate: ModelSignal,
        state: TradingState,
        *,
        equity: float,
        position_quantity: float,
        quote: Quote,
    ) -> ModelSignal:
        if state.halted:
            return ModelSignal(
                as_of=candidate.as_of,
                probability_up=candidate.probability_up,
                target_fraction=0.0,
                action="risk_exit",
                training_samples=candidate.training_samples,
                reasons=(
                    *candidate.reasons,
                    state.halt_reason or "risk_engine_halted",
                ),
            )
        if candidate.action != "hold":
            return candidate
        current_fraction = (
            0.0
            if equity <= 0
            else position_quantity * quote.midpoint / equity
        )
        return ModelSignal(
            as_of=candidate.as_of,
            probability_up=candidate.probability_up,
            target_fraction=min(max(current_fraction, 0.0), self.config.max_position_fraction),
            action=candidate.action,
            training_samples=candidate.training_samples,
            reasons=candidate.reasons,
        )

    @staticmethod
    def _emergency_exit_plan(
        plan: OrderPlan | None, state: TradingState
    ) -> OrderPlan | None:
        if plan is None or plan.side != "sell" or not state.halted:
            return plan
        generation = state.metadata.get("emergency_exit_generation", 0)
        if (
            isinstance(generation, bool)
            or not isinstance(generation, int)
            or generation < 0
            or generation > 9_999
        ):
            raise BrokerError("emergency exit generation requires manual reconciliation")
        return replace(
            plan,
            client_order_id=f"{plan.client_order_id}-e{generation}",
        )

    def _validate_order_identity(
        self,
        order: dict[str, Any],
        payload: dict[str, Any],
        *,
        retryable_terminal_statuses: frozenset[str] = frozenset(),
    ) -> None:
        required = (
            "id",
            "client_order_id",
            "symbol",
            "side",
            "qty",
            "filled_qty",
            "status",
            "time_in_force",
            "extended_hours",
            "limit_price",
        )
        if any(order.get(name) in (None, "") for name in required):
            raise BrokerError("broker order lookup is missing identity fields")
        if str(order["client_order_id"]) != str(payload["client_order_id"]):
            raise BrokerError("broker order client ID does not match the intended order")
        if str(order["symbol"]).upper() != str(payload["symbol"]).upper():
            raise BrokerError("broker order symbol does not match the intended order")
        if str(order["side"]).lower() != str(payload["side"]).lower():
            raise BrokerError("broker order side does not match the intended order")
        try:
            broker_quantity = Decimal(str(order["qty"]))
            intended_quantity = Decimal(str(payload["qty"]))
            filled_quantity = Decimal(str(order["filled_qty"]))
            broker_limit = Decimal(str(order["limit_price"]))
            intended_limit = Decimal(str(payload["limit_price"]))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise BrokerError("broker order has an invalid quantity") from exc
        if not all(
            value.is_finite()
            for value in (
                broker_quantity,
                intended_quantity,
                filled_quantity,
                broker_limit,
                intended_limit,
            )
        ):
            raise BrokerError("broker order has a non-finite quantity")
        if broker_quantity != intended_quantity:
            raise BrokerError("broker order quantity does not match the intended order")
        if filled_quantity < 0 or filled_quantity > broker_quantity:
            raise BrokerError("broker order reports an invalid filled quantity")
        if broker_limit != intended_limit:
            raise BrokerError("broker order limit price does not match the intended order")
        order_types = [order.get("type"), order.get("order_type")]
        present_types = [str(value).lower() for value in order_types if value not in (None, "")]
        if not present_types or any(value != "limit" for value in present_types):
            raise BrokerError("broker order type does not match a limit order")
        if str(order["time_in_force"]).lower() != "day":
            raise BrokerError("broker order time-in-force does not match day")
        if "order_class" not in order or str(order["order_class"]).lower() not in {
            "",
            "simple",
        }:
            raise BrokerError("broker order class does not match simple")
        position_intent = order.get("position_intent")
        if position_intent not in (None, "") and str(position_intent).lower() != str(
            payload["position_intent"]
        ).lower():
            raise BrokerError("broker order position intent does not match")
        if order["extended_hours"] is not False:
            raise BrokerError("broker order unexpectedly permits extended hours")
        status = str(order["status"]).lower()
        if status in TERMINAL_ORDER_STATUSES:
            if status not in retryable_terminal_statuses:
                raise BrokerError("broker order is in a terminal failure state")
            return
        if status in MANUAL_ORDER_STATUSES:
            raise BrokerError("broker order requires manual reconciliation")
        if status not in COMMITTED_ORDER_STATUSES:
            raise BrokerError("broker order has an unknown status")

    @staticmethod
    def _intent_payload(state: TradingState, client_order_id: str) -> dict[str, Any]:
        intent = state.metadata.get("last_intent")
        if not isinstance(intent, dict):
            raise BrokerError("existing broker order has no persisted local intent")
        if str(intent.get("client_order_id") or "") != client_order_id:
            raise BrokerError("existing broker order does not match the persisted intent")
        payload = intent.get("payload")
        if not isinstance(payload, dict):
            raise BrokerError("persisted order intent is missing its exact payload")
        required = {
            "client_order_id",
            "symbol",
            "side",
            "qty",
            "type",
            "time_in_force",
            "order_class",
            "position_intent",
            "limit_price",
            "extended_hours",
        }
        if set(payload) != required:
            raise BrokerError("persisted order payload schema is invalid")
        if payload.get("client_order_id") != client_order_id:
            raise BrokerError("persisted order payload has a different client ID")
        return payload

    def _cancel_open_orders_for_halt(self) -> dict[str, int]:
        responses = self.client.cancel_all_orders()
        failures = 0
        for item in responses:
            try:
                status = int(item.get("status") or 0)
            except (TypeError, ValueError):
                status = 0
            if status < 200 or status >= 300:
                failures += 1
        remaining = self.client.get_open_orders()
        if failures or remaining:
            raise BrokerError(
                "halt is latched, but open-order cancellation could not be verified"
            )
        return {"cancel_responses": len(responses), "remaining_open_orders": 0}

    def _orders_are_risk_reducing(
        self, orders: list[dict[str, Any]], position_quantity: float
    ) -> bool:
        remaining_to_sell = 0.0
        for order in orders:
            if (
                str(order.get("symbol") or "").upper() != self.config.symbol
                or str(order.get("side") or "").lower() != "sell"
            ):
                return False
            try:
                quantity = float(order["qty"])
                filled = float(order.get("filled_qty") or 0)
            except (KeyError, TypeError, ValueError):
                return False
            if (
                not math.isfinite(quantity)
                or not math.isfinite(filled)
                or quantity <= 0
                or filled < 0
                or filled > quantity
            ):
                return False
            remaining_to_sell += quantity - filled
        return remaining_to_sell <= position_quantity + 1e-8

    def _base_result(
        self,
        account: dict[str, Any],
        clock: dict[str, Any],
        clock_time: datetime,
        quote: Quote,
        signal: ModelSignal,
        plan: OrderPlan | None,
    ) -> dict[str, Any]:
        return {
            "paper_only": True,
            "submitted": False,
            "account": {
                "status": account.get("status"),
                "equity": round(float(account.get("equity") or 0), 2),
                "cash": round(float(account.get("cash") or 0), 2),
                "managed_equity_ceiling": self.config.managed_equity_ceiling,
            },
            "clock": {
                "timestamp": clock_time.isoformat(),
                "is_open": bool(clock.get("is_open")),
            },
            "quote": quote.as_dict(),
            "signal": signal.as_dict(),
            "plan": plan.as_dict() if plan else None,
        }

    def _record_rejection(
        self, state: TradingState, result: dict[str, Any], reason: str
    ) -> None:
        self.state_store.save(state)
        self.state_store.append_event(
            {"type": "paper_submission_rejected", "reason": reason, **result}
        )

    def run_once(self, *, submit_paper_order: bool = False) -> dict[str, Any]:
        if self.config.mode != "paper":
            raise BrokerError("paper engine requires mode='paper'")
        state = self.state_store.load()
        account, position_quantity, quote, clock, clock_time = self._snapshot()
        self._bind_account(state, account, position_quantity)
        update_halt_state(self.config, state, account)
        self.state_store.save(state)
        halt_requires_history_bypass = state.halted
        bars: list[Bar] = []
        if not halt_requires_history_bypass:
            bars = self.client.get_daily_bars(
                self.config.symbol,
                start=clock_time - timedelta(days=self.config.history_calendar_days),
                end=clock_time,
                feed=self.config.data_feed,
            )
            asset = self.client.get_asset(self.config.symbol)
            if (
                str(asset.get("status") or "").lower() != "active"
                or asset.get("tradable") is not True
                or asset.get("fractionable") is not True
            ):
                raise BrokerError(
                    "configured symbol is not active, tradable, and fractionable"
                )

        if not halt_requires_history_bypass:
            if bool(clock.get("is_open")):
                bars = [bar for bar in bars if bar.timestamp.date() < clock_time.date()]
            if len(bars) < 220:
                raise BrokerError("fewer than 220 completed daily bars are available")
            trailing_gap_days = (
                clock_time.date() - bars[-1].timestamp.date()
            ).days
            if trailing_gap_days < 0 or trailing_gap_days > 7:
                raise BrokerError(
                    "latest completed daily bar is too stale for paper execution"
                )

        state = self.state_store.load()
        self._bind_account(state, account, position_quantity)
        update_halt_state(self.config, state, account)
        equity = float(account.get("equity") or 0)
        if halt_requires_history_bypass:
            signal = ModelSignal(
                as_of=clock_time.replace(hour=0, minute=0, second=0, microsecond=0),
                probability_up=0.0,
                target_fraction=0.0,
                action="risk_exit",
                training_samples=0,
                reasons=(state.halt_reason or "risk_engine_halted",),
            )
        else:
            signal = self._signal(
                bars,
                state,
                equity=equity,
                position_quantity=position_quantity,
                quote=quote,
            )
        session_date = clock_time.date().isoformat()
        base_plan = build_order_plan(
            self.config,
            signal,
            equity=equity,
            position_quantity=position_quantity,
            quote=quote,
            session_date=session_date,
        )
        plan = self._emergency_exit_plan(base_plan, state)
        result = self._base_result(account, clock, clock_time, quote, signal, plan)

        if plan is None:
            reasons = list(
                evaluate_preflight(
                    self.config,
                    state,
                    account=account,
                    quote=quote,
                    clock=clock,
                    require_open_market=False,
                )
            )
            if state.halted:
                reasons.append(state.halt_reason or "risk_engine_halted")
            result["risk"] = {
                "allowed": not reasons,
                "reasons": reasons or ["no_order_needed"],
            }
        else:
            result["risk"] = evaluate_risk(
                self.config,
                state,
                plan,
                account=account,
                quote=quote,
                clock=clock,
                position_quantity=position_quantity,
                require_open_market=submit_paper_order,
            ).as_dict()

        self.state_store.save(state)
        self.state_store.append_event({"type": "decision", **result})
        if not submit_paper_order:
            return result

        with self.state_store.execution_guard():
            halt_state = self.state_store.load()
            if halt_state.halted:
                halt_position = self._position_quantity(self.client.get_positions())
                halt_orders = self.client.get_open_orders()
                if halt_orders and not self._orders_are_risk_reducing(
                    halt_orders, halt_position
                ):
                    result["halt_cancellation"] = (
                        self._cancel_open_orders_for_halt()
                    )
                    self.state_store.append_event(
                        {"type": "halted_risk_increasing_orders_canceled", **result}
                    )

        if plan is None:
            with self.state_store.execution_guard():
                latest_state = self.state_store.load()
                if self.client.get_open_orders():
                    if latest_state.halted:
                        result["halt_cancellation"] = (
                            self._cancel_open_orders_for_halt()
                        )
                        self.state_store.append_event(
                            {"type": "halted_no_plan_orders_canceled", **result}
                        )
                    else:
                        raise BrokerError(
                            "open broker orders require reconciliation even though no new order is needed"
                        )
            return result

        if os.getenv("RAREIQ_PAPER_ORDER_ACK") != PAPER_ACKNOWLEDGEMENT:
            reason = "missing_paper_order_acknowledgement"
            self._record_rejection(state, result, reason)
            raise BrokerError(
                "paper submission requires RAREIQ_PAPER_ORDER_ACK="
                f"{PAPER_ACKNOWLEDGEMENT}"
            )
        if not bool(result["risk"]["allowed"]):
            reasons = result["risk"]["reasons"]
            reason = "risk_engine_rejected: " + ", ".join(reasons)
            self._record_rejection(state, result, reason)
            raise BrokerError(reason)

        intent_persisted = False
        submission_attempted = False
        halt_cancellation = result.get("halt_cancellation")
        try:
            with self.state_store.execution_guard():
                latest_state = self.state_store.load()
                while True:
                    existing = self.client.get_order_by_client_id(plan.client_order_id)
                    if existing is None:
                        break
                    persisted_payload = self._intent_payload(
                        latest_state, plan.client_order_id
                    )
                    existing_status = str(existing.get("status") or "").lower()
                    retryable_terminal_statuses = (
                        frozenset({"canceled", "expired"})
                        if plan.side == "sell" and latest_state.halted
                        else frozenset()
                    )
                    self._validate_order_identity(
                        existing,
                        persisted_payload,
                        retryable_terminal_statuses=retryable_terminal_statuses,
                    )
                    if (
                        plan.side == "sell"
                        and latest_state.halted
                        and position_quantity > 1e-9
                        and existing_status
                        in {
                            "filled",
                            "done_for_day",
                            "calculated",
                            "canceled",
                            "expired",
                        }
                    ):
                        generation = latest_state.metadata.get(
                            "emergency_exit_generation", 0
                        )
                        if isinstance(generation, bool) or not isinstance(
                            generation, int
                        ):
                            raise BrokerError(
                                "emergency exit generation requires manual reconciliation"
                            )
                        latest_state.metadata["emergency_exit_generation"] = (
                            generation + 1
                        )
                        self.state_store.save(latest_state)
                        if base_plan is None:
                            raise BrokerError("emergency exit plan disappeared")
                        plan = self._emergency_exit_plan(base_plan, latest_state)
                        if plan is None:
                            raise BrokerError("emergency exit plan disappeared")
                        result["plan"] = plan.as_dict()
                        continue
                    latest_state.last_order_date = session_date
                    latest_state.last_client_order_id = plan.client_order_id
                    if str(persisted_payload["side"]).lower() == "buy":
                        latest_state.last_buy_date = session_date
                    self.state_store.save(latest_state)
                    result["reconciled_existing_order"] = True
                    result["order"] = {
                        "id": existing.get("id"),
                        "client_order_id": existing.get("client_order_id"),
                        "status": existing.get("status"),
                        "filled_qty": existing.get("filled_qty"),
                        "limit_price": existing.get("limit_price"),
                    }
                    self.state_store.append_event(
                        {"type": "paper_order_reconciled", **result}
                    )
                    return result

                open_orders = self.client.get_open_orders()
                if open_orders:
                    if latest_state.halted:
                        halt_cancellation = self._cancel_open_orders_for_halt()
                    else:
                        raise BrokerError(
                            "open broker orders require reconciliation before submission"
                        )

                fresh_account, fresh_quantity, fresh_quote, fresh_clock, fresh_time = (
                    self._snapshot()
                )
                latest_state = self.state_store.load()
                self._bind_account(latest_state, fresh_account, fresh_quantity)
                update_halt_state(self.config, latest_state, fresh_account)
                fresh_equity = float(fresh_account["equity"])
                fresh_signal = self._refresh_signal_target(
                    signal,
                    latest_state,
                    equity=fresh_equity,
                    position_quantity=fresh_quantity,
                    quote=fresh_quote,
                )
                fresh_base_plan = build_order_plan(
                    self.config,
                    fresh_signal,
                    equity=fresh_equity,
                    position_quantity=fresh_quantity,
                    quote=fresh_quote,
                    session_date=fresh_time.date().isoformat(),
                )
                fresh_plan = self._emergency_exit_plan(
                    fresh_base_plan, latest_state
                )
                result = self._base_result(
                    fresh_account,
                    fresh_clock,
                    fresh_time,
                    fresh_quote,
                    fresh_signal,
                    fresh_plan,
                )
                if halt_cancellation is not None:
                    result["halt_cancellation"] = halt_cancellation
                if fresh_plan is None:
                    result["risk"] = {
                        "allowed": True,
                        "reasons": ["no_order_needed_after_final_refresh"],
                    }
                    self.state_store.save(latest_state)
                    self.state_store.append_event(
                        {"type": "final_refresh_no_order", **result}
                    )
                    return result
                if fresh_plan.client_order_id != plan.client_order_id:
                    raise BrokerError(
                        "order identity changed during final refresh; rerun safely"
                    )
                if latest_state.halted and fresh_plan.side != "sell":
                    raise BrokerError(
                        "paper order blocked by a concurrently latched halt"
                    )
                preparation_decision = evaluate_risk(
                    self.config,
                    latest_state,
                    fresh_plan,
                    account=fresh_account,
                    quote=fresh_quote,
                    clock=fresh_clock,
                    position_quantity=fresh_quantity,
                    require_open_market=True,
                )
                result["risk"] = preparation_decision.as_dict()
                if not preparation_decision.allowed:
                    raise BrokerError(
                        "preparation risk check rejected the paper order: "
                        + ", ".join(preparation_decision.reasons)
                    )

                raced_order = self.client.get_order_by_client_id(
                    fresh_plan.client_order_id
                )
                if raced_order is not None:
                    persisted_payload = self._intent_payload(
                        latest_state, fresh_plan.client_order_id
                    )
                    self._validate_order_identity(raced_order, persisted_payload)
                    latest_state.last_order_date = fresh_time.date().isoformat()
                    latest_state.last_client_order_id = fresh_plan.client_order_id
                    if str(persisted_payload["side"]).lower() == "buy":
                        latest_state.last_buy_date = fresh_time.date().isoformat()
                    self.state_store.save(latest_state)
                    result["reconciled_existing_order"] = True
                    result["order"] = {
                        "id": raced_order.get("id"),
                        "client_order_id": raced_order.get("client_order_id"),
                        "status": raced_order.get("status"),
                        "filled_qty": raced_order.get("filled_qty"),
                        "limit_price": raced_order.get("limit_price"),
                    }
                    self.state_store.append_event(
                        {"type": "paper_order_reconciled", **result}
                    )
                    return result

                if self.client.get_open_orders():
                    raise BrokerError(
                        "an open broker order appeared during final preflight"
                    )
                final_account, final_quantity, final_quote, final_clock, final_time = (
                    self._snapshot()
                )
                final_clock_observed_at = time.monotonic()
                latest_state = self.state_store.load()
                self._bind_account(latest_state, final_account, final_quantity)
                update_halt_state(self.config, latest_state, final_account)
                final_equity = float(final_account["equity"])
                final_signal = self._refresh_signal_target(
                    signal,
                    latest_state,
                    equity=final_equity,
                    position_quantity=final_quantity,
                    quote=final_quote,
                )
                final_base_plan = build_order_plan(
                    self.config,
                    final_signal,
                    equity=final_equity,
                    position_quantity=final_quantity,
                    quote=final_quote,
                    session_date=final_time.date().isoformat(),
                )
                final_plan = self._emergency_exit_plan(
                    final_base_plan, latest_state
                )
                result = self._base_result(
                    final_account,
                    final_clock,
                    final_time,
                    final_quote,
                    final_signal,
                    final_plan,
                )
                if halt_cancellation is not None:
                    result["halt_cancellation"] = halt_cancellation
                if (
                    final_plan is None
                    or final_plan.client_order_id != fresh_plan.client_order_id
                    or final_plan.side != fresh_plan.side
                ):
                    raise BrokerError(
                        "order direction is no longer required after the final broker snapshot"
                    )
                final_decision = evaluate_risk(
                    self.config,
                    latest_state,
                    final_plan,
                    account=final_account,
                    quote=final_quote,
                    clock=final_clock,
                    position_quantity=final_quantity,
                    require_open_market=True,
                )
                result["risk"] = final_decision.as_dict()
                if not final_decision.allowed:
                    raise BrokerError(
                        "final risk check rejected the paper order: "
                        + ", ".join(final_decision.reasons)
                    )
                limit_price = marketable_limit_price(final_quote, final_plan.side)
                payload = paper_order_payload(final_plan, limit_price=limit_price)
                latest_state.metadata["last_intent"] = {
                    "client_order_id": final_plan.client_order_id,
                    "payload": payload,
                    "plan": final_plan.as_dict(),
                    "signal_as_of": final_signal.as_of.isoformat(),
                    "status": "prepared",
                }
                self.state_store.save(latest_state)
                intent_persisted = True
                self.state_store.append_event(
                    {"type": "paper_order_intent_persisted", **result}
                )
                if self.client.get_open_orders():
                    raise BrokerError(
                        "an open broker order appeared immediately before submission"
                    )
                latest_state = self.state_store.load()
                if latest_state.halted and final_plan.side != "sell":
                    raise BrokerError(
                        "paper order blocked by a concurrently persisted halt"
                    )
                if self.state_store.kill_switch_latched() and final_plan.side != "sell":
                    raise BrokerError(
                        "paper order blocked by a concurrent kill-switch request"
                    )
                elapsed_since_clock = (
                    time.monotonic()
                    - final_clock_observed_at
                    + ORDER_TRANSMISSION_MARGIN_SECONDS
                )
                effective_time = final_time + timedelta(seconds=elapsed_since_clock)
                effective_open = bool(final_clock["is_open"])
                if effective_open:
                    next_close = datetime.fromisoformat(
                        str(final_clock["next_close"]).replace("Z", "+00:00")
                    )
                    if effective_time >= next_close:
                        effective_open = False
                immediate_clock = {
                    **final_clock,
                    "timestamp": effective_time.isoformat(),
                    "is_open": effective_open,
                }
                immediate_decision = evaluate_risk(
                    self.config,
                    latest_state,
                    final_plan,
                    account=final_account,
                    quote=final_quote,
                    clock=immediate_clock,
                    position_quantity=final_quantity,
                    require_open_market=True,
                )
                result["risk"] = immediate_decision.as_dict()
                if not immediate_decision.allowed:
                    raise BrokerError(
                        "immediate submission check rejected the paper order: "
                        + ", ".join(immediate_decision.reasons)
                    )
                submission_attempted = True
                try:
                    order = self.client.submit_marketable_limit_order(
                        final_plan, limit_price=limit_price
                    )
                except BrokerError:
                    order = self.client.get_order_by_client_id(
                        final_plan.client_order_id
                    )
                    if order is None:
                        raise
                    result["reconciled_after_uncertain_submission"] = True
                self._validate_order_identity(order, payload)
                execution_date = final_time.date().isoformat()

                final_status = str(order.get("status") or "")
                latest_state.last_order_date = execution_date
                latest_state.last_client_order_id = final_plan.client_order_id
                if final_plan.side == "buy":
                    latest_state.last_buy_date = execution_date
                persisted_intent = latest_state.metadata.get("last_intent")
                if isinstance(persisted_intent, dict):
                    persisted_intent["status"] = final_status
                result["submitted"] = submission_attempted
                result["order"] = {
                    "id": order.get("id"),
                    "client_order_id": order.get("client_order_id"),
                    "status": order.get("status"),
                    "filled_qty": order.get("filled_qty"),
                    "limit_price": order.get("limit_price"),
                }
                self.state_store.save(latest_state)
            self.state_store.append_event({"type": "paper_submission", **result})
            return result
        except (BrokerError, RuntimeError) as exc:
            if intent_persisted:
                current_state = self.state_store.load()
                last_intent = current_state.metadata.get("last_intent")
                if (
                    isinstance(last_intent, dict)
                    and last_intent.get("client_order_id") == plan.client_order_id
                    and last_intent.get("status") in {"prepared", "rejected"}
                ):
                    last_intent["status"] = (
                        "submission_error" if submission_attempted else "rejected"
                    )
                    self.state_store.save(current_state)
            self.state_store.append_event(
                {
                    "type": "paper_submission_error",
                    "reason": str(exc)[:300],
                    **result,
                }
            )
            raise
