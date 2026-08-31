from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest

from rareiq.trading.config import TradingConfig
from rareiq.trading.data import _eastern_utc_offset
from rareiq.trading.models import Bar
from rareiq.trading.strategy import SmaRegimeStrategy, WalkForwardLogisticStrategy


def bars_with_growth(count: int, daily_growth: float = 0.0005) -> list[Bar]:
    session_date = date(2020, 1, 2)
    price = 100.0
    bars: list[Bar] = []
    for index in range(count):
        while session_date.weekday() >= 5:
            session_date += timedelta(days=1)
        offset = timezone(timedelta(hours=_eastern_utc_offset(session_date)))
        price *= 1.0 + daily_growth + (0.0002 if index % 7 == 0 else -0.00005)
        bars.append(
            Bar(
                timestamp=datetime.combine(session_date, time.min, tzinfo=offset),
                open=price * 0.999,
                high=price * 1.002,
                low=price * 0.998,
                close=price,
                volume=1_000_000 + index,
            )
        )
        session_date += timedelta(days=1)
    return bars


def test_sma_baseline_waits_for_completed_history() -> None:
    strategy = SmaRegimeStrategy(TradingConfig())

    assert strategy.signal(bars_with_growth(199)).action == "wait"
    signal = strategy.signal(bars_with_growth(200))
    assert signal.action == "enter_or_add"
    assert signal.target_fraction == 0.25


def test_walk_forward_model_is_deterministic() -> None:
    config = TradingConfig(
        strategy="walk_forward_logistic",
        minimum_training_samples=100,
        training_window_bars=300,
    )
    bars = bars_with_growth(360)

    first = WalkForwardLogisticStrategy(config).signal(bars)
    second = WalkForwardLogisticStrategy(config).signal(bars)

    assert first.as_dict() == second.as_dict()
    assert first.training_samples >= 100
    assert 0 <= first.probability_up <= 1


def test_future_data_cannot_change_an_already_computed_signal() -> None:
    config = TradingConfig(
        strategy="walk_forward_logistic",
        minimum_training_samples=100,
        training_window_bars=300,
    )
    history = bars_with_growth(340)
    original = WalkForwardLogisticStrategy(config).signal(history)
    future = bars_with_growth(380, daily_growth=-0.001)[340:]

    repeated = WalkForwardLogisticStrategy(config).signal((history + future)[:340])

    assert repeated.as_dict() == original.as_dict()


def test_strategy_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="at least one bar"):
        SmaRegimeStrategy(TradingConfig()).signal([])


def test_bar_rejects_nan_market_data() -> None:
    with pytest.raises(ValueError, match="finite"):
        Bar(
            timestamp=datetime.now(timezone.utc),
            open=float("nan"),
            high=1,
            low=1,
            close=1,
            volume=1,
        )
