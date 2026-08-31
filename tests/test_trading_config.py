from __future__ import annotations

import pytest

from rareiq.trading.config import TradingConfig, TradingConfigError


def test_default_trading_config_is_small_and_research_only() -> None:
    config = TradingConfig()

    assert config.mode == "research"
    assert config.allowed_symbols == ("SPY",)
    assert config.starting_cash == 100
    assert config.max_position_fraction == 0.25
    assert config.max_order_fraction == 0.10


@pytest.mark.parametrize(
    "override",
    [
        {"mode": "live"},
        {"starting_cash": 101},
        {"managed_equity_ceiling": 251},
        {"max_position_fraction": 0.36},
        {"rebalance_drift_fraction": 0.051},
        {"max_order_fraction": 0.11},
        {"daily_loss_limit_fraction": 0.021},
        {"max_drawdown_fraction": 0.11},
        {"data_feed": "sip"},
        {"managed_equity_ceiling": float("nan")},
        {"minimum_training_samples": float("nan")},
        {"history_calendar_days": 2200.0},
        {"prediction_horizon_bars": True},
    ],
)
def test_config_rejects_settings_outside_phase_one_envelope(
    override: dict[str, object],
) -> None:
    with pytest.raises(TradingConfigError):
        TradingConfig(**override)


def test_config_rejects_unknown_keys() -> None:
    with pytest.raises(TradingConfigError, match="unknown configuration keys"):
        TradingConfig.from_mapping({"leverage": 10})


def test_phase_one_rejects_an_aggregate_multi_symbol_universe() -> None:
    with pytest.raises(TradingConfigError, match="SPY only"):
        TradingConfig(allowed_symbols=("SPY", "QQQ"))
    with pytest.raises(TradingConfigError, match="SPY only"):
        TradingConfig(symbol="QQQ", allowed_symbols=("QQQ",))


def test_paper_mode_requires_one_canonical_state_and_daily_model_refit(tmp_path) -> None:
    with pytest.raises(TradingConfigError, match="canonical"):
        TradingConfig(mode="paper", runtime_directory="runtime/alternate")
    with pytest.raises(TradingConfigError, match="canonical"):
        TradingConfig(mode="research", runtime_directory="runtime/alternate")
    with pytest.raises(TradingConfigError, match="backtest parity"):
        TradingConfig(
            mode="paper",
            strategy="walk_forward_logistic",
            retrain_every_bars=5,
        )
