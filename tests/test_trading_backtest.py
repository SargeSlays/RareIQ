from __future__ import annotations

from rareiq.trading.backtest import Backtester
from rareiq.trading.config import TradingConfig
from tests.test_trading_strategy import bars_with_growth


def test_backtest_caps_exposure_and_preserves_cash_buffer() -> None:
    config = TradingConfig()
    result = Backtester(config).run(bars_with_growth(500))

    assert result.metrics["max_observed_position_percent"] <= 27.1
    assert min(item["cash"] for item in result.equity_curve) >= 9.99
    assert all(item["side"] in {"buy", "sell"} for item in result.trades)
    assert result.metrics["trade_count"] > 0


def test_stress_costs_do_not_outperform_base_costs_on_same_fills() -> None:
    config = TradingConfig()
    bars = bars_with_growth(500)

    base = Backtester(config).run(bars)
    stress = Backtester(config, slippage_bps=25, minimum_order_fee=0.01).run(bars)

    assert stress.metrics["final_equity"] <= base.metrics["final_equity"]
    assert stress.metrics["trade_count"] > 0


def test_stress_slippage_can_be_set_above_high_configured_base_cost() -> None:
    config = TradingConfig(slippage_bps=50)
    bars = bars_with_growth(500)

    base = Backtester(config).run(bars)
    stress = Backtester(config, slippage_bps=65, minimum_order_fee=0.01).run(bars)

    assert stress.metrics["final_equity"] <= base.metrics["final_equity"]


def test_backtest_is_byte_stable_for_same_inputs() -> None:
    config = TradingConfig()
    bars = bars_with_growth(300)

    first = Backtester(config).run(bars).as_dict(include_equity_curve=True)
    second = Backtester(config).run(bars).as_dict(include_equity_curve=True)

    assert first == second


def test_backtest_halts_and_flattens_after_managed_equity_ceiling() -> None:
    config = TradingConfig(managed_equity_ceiling=101)

    result = Backtester(config).run(bars_with_growth(500, daily_growth=0.01))

    assert result.metrics["halted"] is True
    assert result.metrics["halt_reason"] == "managed_equity_review_halt"
    assert result.trades[-1]["side"] == "sell"
    assert result.equity_curve[-1]["position_value"] == 0
