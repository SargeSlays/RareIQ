from __future__ import annotations

from datetime import datetime, timezone

from rareiq.trading.config import TradingConfig
from rareiq.trading.models import ModelSignal, Quote, TradingState
from rareiq.trading.risk import build_order_plan, evaluate_risk


NOW = datetime(2026, 8, 27, 13, 32, tzinfo=timezone.utc)


def market_clock() -> dict[str, object]:
    return {
        "timestamp": NOW.isoformat(),
        "is_open": True,
        "next_close": "2026-08-27T16:00:00-04:00",
    }


def signal(target: float) -> ModelSignal:
    return ModelSignal(
        as_of=datetime(2026, 8, 26, tzinfo=timezone.utc),
        probability_up=0.7,
        target_fraction=target,
        action="test",
        training_samples=200,
    )


def paper_config() -> TradingConfig:
    return TradingConfig(mode="paper")


def account(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "status": "ACTIVE",
        "equity": "100.00",
        "last_equity": "100.00",
        "cash": "100.00",
        "trading_blocked": False,
        "account_blocked": False,
        "trade_suspended_by_user": False,
    }
    value.update(overrides)
    return value


def test_order_plan_is_deterministic_and_capped_at_ten_percent() -> None:
    config = paper_config()
    quote = Quote(timestamp=NOW, bid=499.99, ask=500.01)

    first = build_order_plan(
        config,
        signal(0.25),
        equity=100,
        position_quantity=0,
        quote=quote,
        session_date="2026-08-27",
    )
    second = build_order_plan(
        config,
        signal(0.25),
        equity=100,
        position_quantity=0,
        quote=quote,
        session_date="2026-08-27",
    )

    assert first is not None
    assert first.as_dict() == second.as_dict()
    assert first.notional == 10
    assert first.side == "buy"


def test_fresh_small_paper_order_passes_risk_checks() -> None:
    config = paper_config()
    quote = Quote(timestamp=NOW, bid=499.99, ask=500.01)
    plan = build_order_plan(
        config,
        signal(0.25),
        equity=100,
        position_quantity=0,
        quote=quote,
        session_date="2026-08-27",
    )
    assert plan is not None

    decision = evaluate_risk(
        config,
        TradingState(),
        plan,
        account=account(),
        quote=quote,
        clock=market_clock(),
        position_quantity=0,
        require_open_market=True,
    )

    assert decision.allowed


def test_stale_quote_and_default_100k_paper_balance_fail_closed() -> None:
    config = paper_config()
    quote = Quote(
        timestamp=datetime(2026, 8, 27, 16, 59, 40, tzinfo=timezone.utc),
        bid=499.99,
        ask=500.01,
    )
    plan = build_order_plan(
        config,
        signal(0.25),
        equity=100_000,
        position_quantity=0,
        quote=quote,
        session_date="2026-08-27",
    )
    assert plan is not None

    decision = evaluate_risk(
        config,
        TradingState(),
        plan,
        account=account(equity="100000", cash="100000", last_equity="100000"),
        quote=quote,
        clock=market_clock(),
        position_quantity=0,
        require_open_market=True,
    )

    assert not decision.allowed
    assert "quote_is_stale" in decision.reasons
    assert "managed_equity_ceiling_exceeded" in decision.reasons


def test_sticky_halt_blocks_new_risk_but_allows_flattening() -> None:
    config = paper_config()
    quote = Quote(timestamp=NOW, bid=99.99, ask=100.01)
    state = TradingState(high_water_mark=110, halted=True, halt_reason="manual_kill_switch")
    buy = build_order_plan(
        config,
        signal(0.25),
        equity=100,
        position_quantity=0,
        quote=quote,
        session_date="2026-08-27",
    )
    sell = build_order_plan(
        config,
        signal(0),
        equity=100,
        position_quantity=0.1,
        quote=quote,
        session_date="2026-08-27",
    )
    assert buy is not None and sell is not None

    buy_decision = evaluate_risk(
        config,
        state,
        buy,
        account=account(cash="90"),
        quote=quote,
        clock=market_clock(),
        position_quantity=0,
        require_open_market=True,
    )
    sell_decision = evaluate_risk(
        config,
        state,
        sell,
        account=account(cash="90"),
        quote=quote,
        clock=market_clock(),
        position_quantity=0.1,
        require_open_market=True,
    )

    assert not buy_decision.allowed
    assert "manual_kill_switch" in buy_decision.reasons
    assert sell_decision.allowed


def test_same_day_emergency_sell_overrides_daily_order_limit() -> None:
    config = paper_config()
    quote = Quote(timestamp=NOW, bid=99.99, ask=100.01)
    state = TradingState(
        high_water_mark=100,
        halted=True,
        halt_reason="daily_loss_halt",
        last_order_date="2026-08-27",
    )
    sell = build_order_plan(
        config,
        signal(0),
        equity=100,
        position_quantity=0.1,
        quote=quote,
        session_date="2026-08-27",
    )
    assert sell is not None

    decision = evaluate_risk(
        config,
        state,
        sell,
        account=account(cash="90"),
        quote=quote,
        clock=market_clock(),
        position_quantity=0.1,
        require_open_market=True,
    )

    assert decision.allowed
    assert "daily_order_limit_reached" not in decision.reasons


def test_routine_same_day_sell_is_blocked_but_halted_exit_is_allowed() -> None:
    config = paper_config()
    quote = Quote(timestamp=NOW, bid=99.99, ask=100.01)
    sell = build_order_plan(
        config,
        signal(0),
        equity=100,
        position_quantity=0.1,
        quote=quote,
        session_date="2026-08-27",
    )
    assert sell is not None
    routine_state = TradingState(last_buy_date="2026-08-27")
    halted_state = TradingState(
        halted=True,
        halt_reason="daily_loss_halt",
        last_buy_date="2026-08-27",
    )

    routine = evaluate_risk(
        config,
        routine_state,
        sell,
        account=account(cash="90"),
        quote=quote,
        clock=market_clock(),
        position_quantity=0.1,
        require_open_market=True,
    )
    emergency = evaluate_risk(
        config,
        halted_state,
        sell,
        account=account(cash="90"),
        quote=quote,
        clock=market_clock(),
        position_quantity=0.1,
        require_open_market=True,
    )

    assert "routine_same_day_round_trip_blocked" in routine.reasons
    assert emergency.allowed


def test_midday_entry_is_blocked_but_emergency_sell_is_allowed() -> None:
    config = paper_config()
    midday = datetime(2026, 8, 27, 17, 0, tzinfo=timezone.utc)
    quote = Quote(timestamp=midday, bid=99.99, ask=100.01)
    clock = {
        "timestamp": midday.isoformat(),
        "is_open": True,
        "next_close": "2026-08-27T16:00:00-04:00",
    }
    buy = build_order_plan(
        config,
        signal(0.25),
        equity=100,
        position_quantity=0,
        quote=quote,
        session_date="2026-08-27",
    )
    sell = build_order_plan(
        config,
        signal(0),
        equity=100,
        position_quantity=0.1,
        quote=quote,
        session_date="2026-08-27",
    )
    assert buy is not None and sell is not None

    buy_decision = evaluate_risk(
        config,
        TradingState(),
        buy,
        account=account(),
        quote=quote,
        clock=clock,
        position_quantity=0,
        require_open_market=True,
    )
    sell_decision = evaluate_risk(
        config,
        TradingState(halted=True, halt_reason="manual_kill_switch"),
        sell,
        account=account(cash="90"),
        quote=quote,
        clock=clock,
        position_quantity=0.1,
        require_open_market=True,
    )

    assert "outside_opening_execution_window" in buy_decision.reasons
    assert sell_decision.allowed


def test_equity_review_ceiling_forces_exit_without_trapping_sell() -> None:
    config = paper_config()
    quote = Quote(timestamp=NOW, bid=99.99, ask=100.01)
    state = TradingState(high_water_mark=126)
    sell = build_order_plan(
        config,
        signal(0),
        equity=126,
        position_quantity=0.1,
        quote=quote,
        session_date="2026-08-27",
    )
    assert sell is not None

    decision = evaluate_risk(
        config,
        state,
        sell,
        account=account(equity="126", cash="116", last_equity="126"),
        quote=quote,
        clock=market_clock(),
        position_quantity=0.1,
        require_open_market=True,
    )

    assert state.halted
    assert state.halt_reason == "managed_equity_review_halt"
    assert decision.allowed


def test_missing_account_safety_flag_and_malformed_clock_fail_closed() -> None:
    config = paper_config()
    quote = Quote(timestamp=NOW, bid=499.99, ask=500.01)
    plan = build_order_plan(
        config,
        signal(0.25),
        equity=100,
        position_quantity=0,
        quote=quote,
        session_date="2026-08-27",
    )
    assert plan is not None
    incomplete_account = account()
    incomplete_account.pop("trade_suspended_by_user")
    malformed_clock = market_clock()
    malformed_clock["is_open"] = "true"

    decision = evaluate_risk(
        config,
        TradingState(),
        plan,
        account=incomplete_account,
        quote=quote,
        clock=malformed_clock,
        position_quantity=0,
        require_open_market=True,
    )

    assert not decision.allowed
    assert "broker_account_block_flags_unavailable" in decision.reasons
    assert "market_clock_open_flag_invalid" in decision.reasons


def test_missing_last_equity_latches_an_invalid_balance_halt() -> None:
    config = paper_config()
    quote = Quote(timestamp=NOW, bid=499.99, ask=500.01)
    plan = build_order_plan(
        config,
        signal(0.25),
        equity=100,
        position_quantity=0,
        quote=quote,
        session_date="2026-08-27",
    )
    assert plan is not None
    state = TradingState()
    incomplete_account = account()
    incomplete_account.pop("last_equity")

    decision = evaluate_risk(
        config,
        state,
        plan,
        account=incomplete_account,
        quote=quote,
        clock=market_clock(),
        position_quantity=0,
        require_open_market=True,
    )

    assert not decision.allowed
    assert state.halted
    assert state.halt_reason == "invalid_account_balance_halt"
