from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Any

import numpy as np

from rareiq.trading.config import TradingConfig
from rareiq.trading.data import validate_bars
from rareiq.trading.models import Bar, ModelSignal
from rareiq.trading.strategy import build_strategy


@dataclass(frozen=True, slots=True)
class BacktestResult:
    metrics: dict[str, Any]
    trades: tuple[dict[str, Any], ...]
    equity_curve: tuple[dict[str, Any], ...]

    def as_dict(self, include_equity_curve: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "metrics": dict(self.metrics),
            "trades": [dict(item) for item in self.trades],
        }
        if include_equity_curve:
            result["equity_curve"] = [dict(item) for item in self.equity_curve]
        return result


class Backtester:
    """Next-session, fractional-share simulator with conservative costs."""

    def __init__(
        self,
        config: TradingConfig,
        *,
        slippage_bps: float | None = None,
        minimum_order_fee: float = 0.0,
    ) -> None:
        self.config = config
        self.slippage_bps = (
            config.slippage_bps if slippage_bps is None else float(slippage_bps)
        )
        self.minimum_order_fee = float(minimum_order_fee)

    def _cost(self, notional: float) -> float:
        variable = notional * self.config.fee_bps / 10_000.0
        return max(variable, self.minimum_order_fee) if notional > 0 else 0.0

    def run(self, source_bars: list[Bar]) -> BacktestResult:
        bars = validate_bars(source_bars)
        if len(bars) < 220:
            raise ValueError("backtest requires at least 220 daily bars")

        strategy = build_strategy(self.config)
        cash = float(self.config.starting_cash)
        quantity = 0.0
        pending_signal: ModelSignal | None = None
        high_water = cash
        halted = False
        halt_reason = ""
        previous_equity = cash
        trades: list[dict[str, Any]] = []
        curve: list[dict[str, Any]] = []
        slippage = self.slippage_bps / 10_000.0
        max_observed_fraction = 0.0
        position_episode_open = False
        completed_round_trips = 0

        for index, bar in enumerate(bars):
            open_equity = cash + quantity * bar.open
            open_drawdown = (
                0.0 if high_water <= 0 else 1.0 - open_equity / high_water
            )
            open_daily_return = (
                0.0 if previous_equity <= 0 else open_equity / previous_equity - 1.0
            )
            if (
                not halted
                and open_equity > self.config.managed_equity_ceiling + 0.01
            ):
                halted = True
                halt_reason = "managed_equity_review_halt"
            elif not halted and open_drawdown >= self.config.max_drawdown_fraction:
                halted = True
                halt_reason = "max_drawdown_halt"
            elif (
                not halted
                and open_daily_return <= -self.config.daily_loss_limit_fraction
            ):
                halted = True
                halt_reason = "daily_loss_halt"
            if pending_signal is not None:
                target_fraction = 0.0 if halted else pending_signal.target_fraction
                target_value = open_equity * target_fraction
                current_value = quantity * bar.open
                difference = target_value - current_value
                current_open_fraction = (
                    0.0 if open_equity <= 0 else current_value / open_equity
                )
                within_sell_drift = (
                    target_fraction > 0
                    and difference < 0
                    and current_open_fraction
                    <= min(
                        0.35,
                        target_fraction + self.config.rebalance_drift_fraction,
                    )
                )

                if difference >= 1.0 and not halted:
                    order_cap = open_equity * self.config.max_order_fraction
                    reserved_cash = open_equity * self.config.cash_buffer_fraction
                    spendable = max(0.0, cash - reserved_cash)
                    requested = min(difference, order_cap, spendable)
                    fee_rate = self.config.fee_bps / 10_000.0
                    requested = requested / (1.0 + fee_rate)
                    if requested >= 1.0:
                        fill_price = bar.open * (1.0 + slippage)
                        bought = requested / fill_price
                        fee = self._cost(requested)
                        total = requested + fee
                        if total <= cash + 1e-9:
                            opening_new_episode = quantity <= 1e-10
                            cash -= total
                            quantity += bought
                            if opening_new_episode:
                                position_episode_open = True
                            trades.append(
                                {
                                    "timestamp": bar.timestamp.isoformat(),
                                    "side": "buy",
                                    "notional": round(requested, 4),
                                    "quantity": round(bought, 9),
                                    "fill_price": round(fill_price, 6),
                                    "fee": round(fee, 6),
                                    "signal_as_of": pending_signal.as_of.isoformat(),
                                    "reason": pending_signal.action,
                                }
                            )
                elif difference <= -0.01 and quantity > 0 and not within_sell_drift:
                    fill_price = bar.open * (1.0 - slippage)
                    if target_fraction <= 0 or halted:
                        sold = quantity
                    else:
                        sold = min(quantity, abs(difference) / fill_price)
                    proceeds = sold * fill_price
                    fee = self._cost(proceeds)
                    cash += max(0.0, proceeds - fee)
                    quantity -= sold
                    if quantity < 1e-10:
                        quantity = 0.0
                        if position_episode_open:
                            completed_round_trips += 1
                            position_episode_open = False
                    trades.append(
                        {
                            "timestamp": bar.timestamp.isoformat(),
                            "side": "sell",
                            "notional": round(proceeds, 4),
                            "quantity": round(sold, 9),
                            "fill_price": round(fill_price, 6),
                            "fee": round(fee, 6),
                            "signal_as_of": pending_signal.as_of.isoformat(),
                            "reason": halt_reason or pending_signal.action,
                        }
                    )

            close_equity = cash + quantity * bar.close
            high_water = max(high_water, close_equity)
            drawdown = 0.0 if high_water <= 0 else 1.0 - close_equity / high_water
            daily_return = (
                0.0 if previous_equity <= 0 else close_equity / previous_equity - 1.0
            )
            current_fraction = (
                0.0 if close_equity <= 0 else quantity * bar.close / close_equity
            )
            max_observed_fraction = max(max_observed_fraction, current_fraction)

            if (
                not halted
                and close_equity > self.config.managed_equity_ceiling + 0.01
            ):
                halted = True
                halt_reason = "managed_equity_review_halt"
            elif not halted and drawdown >= self.config.max_drawdown_fraction:
                halted = True
                halt_reason = "max_drawdown_halt"
            elif not halted and daily_return <= -self.config.daily_loss_limit_fraction:
                halted = True
                halt_reason = "daily_loss_halt"

            curve.append(
                {
                    "timestamp": bar.timestamp.isoformat(),
                    "equity": round(close_equity, 6),
                    "cash": round(cash, 6),
                    "position_value": round(quantity * bar.close, 6),
                    "drawdown": round(drawdown, 8),
                    "halted": halted,
                }
            )

            pending_signal = strategy.signal(bars[: index + 1], current_fraction)
            if halted:
                pending_signal = ModelSignal(
                    as_of=pending_signal.as_of,
                    probability_up=pending_signal.probability_up,
                    target_fraction=0.0,
                    action="risk_exit",
                    training_samples=pending_signal.training_samples,
                    reasons=(*pending_signal.reasons, halt_reason),
                )
            previous_equity = close_equity

        final_equity = float(curve[-1]["equity"])
        equities = np.asarray([float(item["equity"]) for item in curve], dtype=np.float64)
        returns = np.divide(
            equities[1:],
            equities[:-1],
            out=np.ones_like(equities[1:]),
            where=equities[:-1] != 0,
        ) - 1.0
        running_high = np.maximum.accumulate(equities)
        drawdowns = 1.0 - np.divide(
            equities, running_high, out=np.zeros_like(equities), where=running_high != 0
        )
        elapsed_days = (
            bars[-1].timestamp.timestamp() - bars[0].timestamp.timestamp()
        ) / 86_400.0
        years = max(elapsed_days / 365.2425, 1.0 / 252.0)
        total_return = final_equity / self.config.starting_cash - 1.0
        annualized = (
            (final_equity / self.config.starting_cash) ** (1.0 / years) - 1.0
            if final_equity > 0
            else -1.0
        )
        volatility = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0
        sharpe = (
            float(np.mean(returns) / volatility * sqrt(252.0))
            if volatility > 0
            else 0.0
        )
        benchmark_fraction = self.config.max_position_fraction
        benchmark_final = self.config.starting_cash * (
            1.0
            - benchmark_fraction
            + benchmark_fraction * bars[-1].close / bars[0].close
        )
        metrics = {
            "strategy": self.config.strategy,
            "walk_forward": self.config.strategy == "walk_forward_logistic",
            "bars": len(bars),
            "start": bars[0].timestamp.isoformat(),
            "end": bars[-1].timestamp.isoformat(),
            "elapsed_calendar_years": round(years, 6),
            "starting_cash": round(self.config.starting_cash, 2),
            "final_equity": round(final_equity, 4),
            "total_return_percent": round(total_return * 100.0, 4),
            "annualized_return_percent": round(annualized * 100.0, 4),
            "max_drawdown_percent": round(float(np.max(drawdowns)) * 100.0, 4),
            "sharpe_zero_rate": round(sharpe, 4),
            "trade_count": len(trades),
            "completed_round_trips": completed_round_trips,
            "max_observed_position_percent": round(max_observed_fraction * 100.0, 4),
            "halted": halted,
            "halt_reason": halt_reason,
            "assumed_slippage_bps_one_way": self.slippage_bps,
            "assumed_minimum_order_fee": self.minimum_order_fee,
            "fraction_matched_buy_hold_final": round(benchmark_final, 4),
            "cash_benchmark_final": round(self.config.starting_cash, 2),
        }
        return BacktestResult(metrics, tuple(trades), tuple(curve))
