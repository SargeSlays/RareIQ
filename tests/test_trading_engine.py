from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest

import rareiq.trading.config as trading_config_module
from rareiq.trading.broker import BrokerError, paper_order_payload
from rareiq.trading.config import TradingConfig
from rareiq.trading.data import _eastern_utc_offset
from rareiq.trading.engine import PAPER_ACKNOWLEDGEMENT, PaperTradingEngine
from rareiq.trading.models import Bar, OrderPlan, Quote, TradingState
from rareiq.trading.risk import TradingStateStore


NOW = datetime(2026, 8, 27, 13, 32, tzinfo=timezone.utc)


def completed_bars() -> list[Bar]:
    price = 100.0
    result: list[Bar] = []
    session_dates: list[date] = []
    candidate = date(2026, 8, 26)
    while len(session_dates) < 240:
        if candidate.weekday() < 5:
            session_dates.append(candidate)
        candidate -= timedelta(days=1)
    session_dates.reverse()
    for session_date in session_dates:
        offset = timezone(timedelta(hours=_eastern_utc_offset(session_date)))
        price *= 1.001
        result.append(
            Bar(
                timestamp=datetime.combine(session_date, time.min, tzinfo=offset),
                open=price * 0.999,
                high=price * 1.002,
                low=price * 0.998,
                close=price,
                volume=1_000_000,
            )
        )
    return result


class FakePaperClient:
    def __init__(
        self,
        *,
        uncertain: bool = False,
        account_id: str = "paper-account-100",
        equity: float = 100.0,
    ) -> None:
        self.uncertain = uncertain
        self.account_id = account_id
        self.equity = equity
        self.lookup_calls = 0
        self.submit_calls = 0
        self.last_plan: OrderPlan | None = None
        self.last_payload: dict[str, object] | None = None

    def get_account(self) -> dict[str, object]:
        return {
            "id": self.account_id,
            "status": "ACTIVE",
            "equity": str(self.equity),
            "last_equity": str(self.equity),
            "cash": str(self.equity),
            "trading_blocked": False,
            "account_blocked": False,
            "trade_suspended_by_user": False,
        }

    def get_clock(self) -> dict[str, object]:
        return {
            "timestamp": NOW.isoformat(),
            "is_open": True,
            "next_close": "2026-08-27T16:00:00-04:00",
        }

    def get_daily_bars(self, *_: object, **__: object) -> list[Bar]:
        return completed_bars()

    def get_positions(self) -> list[dict[str, object]]:
        return []

    def get_asset(self, *_: object, **__: object) -> dict[str, object]:
        return {"status": "active", "tradable": True, "fractionable": True}

    def get_latest_quote(self, *_: object, **__: object) -> Quote:
        return Quote(timestamp=NOW, bid=499.99, ask=500.01)

    def get_order_by_client_id(self, client_order_id: str) -> dict[str, object] | None:
        self.lookup_calls += 1
        if self.uncertain and self.submit_calls:
            assert self.last_plan is not None
            assert self.last_payload is not None
            return {
                "id": "accepted-despite-timeout",
                "client_order_id": client_order_id,
                "symbol": self.last_plan.symbol,
                "side": self.last_plan.side,
                "qty": self.last_payload["qty"],
                "filled_qty": "0",
                "status": "accepted",
                "limit_price": self.last_payload["limit_price"],
                "type": "limit",
                "time_in_force": "day",
                "order_class": "simple",
                "position_intent": self.last_payload["position_intent"],
                "extended_hours": False,
            }
        return None

    def get_open_orders(self) -> list[dict[str, object]]:
        return []

    def submit_marketable_limit_order(
        self, plan: OrderPlan, *, limit_price: float
    ) -> dict[str, object]:
        self.submit_calls += 1
        self.last_plan = plan
        self.last_payload = paper_order_payload(plan, limit_price=limit_price)
        if self.uncertain:
            raise BrokerError("simulated timeout")
        return {
            "id": "paper-order-1",
            "client_order_id": plan.client_order_id,
            "symbol": plan.symbol,
            "side": plan.side,
            "qty": self.last_payload["qty"],
            "filled_qty": "0",
            "status": "accepted",
            "limit_price": f"{limit_price:.2f}",
            "type": "limit",
            "time_in_force": "day",
            "order_class": "simple",
            "position_intent": self.last_payload["position_intent"],
            "extended_hours": False,
        }


def test_engine_submits_only_after_explicit_paper_ack(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(trading_config_module, "PROJECT_ROOT", tmp_path)
    config = TradingConfig(mode="paper")
    client = FakePaperClient()
    monkeypatch.setenv("RAREIQ_PAPER_ORDER_ACK", PAPER_ACKNOWLEDGEMENT)
    store = TradingStateStore(config.runtime_directory)

    result = PaperTradingEngine(
        config, client, store
    ).run_once(submit_paper_order=True)

    assert result["paper_only"] is True
    assert result["submitted"] is True
    assert client.submit_calls == 1
    assert (tmp_path / "runtime" / "trading" / "journal.jsonl").exists()


def test_uncertain_submission_reuses_client_id_instead_of_resubmitting(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(trading_config_module, "PROJECT_ROOT", tmp_path)
    config = TradingConfig(mode="paper")
    client = FakePaperClient(uncertain=True)
    monkeypatch.setenv("RAREIQ_PAPER_ORDER_ACK", PAPER_ACKNOWLEDGEMENT)

    result = PaperTradingEngine(
        config, client, TradingStateStore(config.runtime_directory)
    ).run_once(submit_paper_order=True)

    assert result["reconciled_after_uncertain_submission"] is True
    assert client.submit_calls == 1
    assert client.lookup_calls == 3


def test_missing_ack_is_persisted_and_journaled(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(trading_config_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("RAREIQ_PAPER_ORDER_ACK", raising=False)
    config = TradingConfig(mode="paper")
    store = TradingStateStore(config.runtime_directory)

    with pytest.raises(BrokerError, match="requires RAREIQ_PAPER_ORDER_ACK"):
        PaperTradingEngine(config, FakePaperClient(), store).run_once(
            submit_paper_order=True
        )

    recovered = store.load()
    journal = store.journal_path.read_text(encoding="utf-8")
    assert recovered.metadata["broker_account_id"] == "paper-account-100"
    assert '"type":"decision"' in journal
    assert '"type":"paper_submission_rejected"' in journal
    assert "missing_paper_order_acknowledgement" in journal


def test_first_run_requires_exact_100_dollar_flat_account(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(trading_config_module, "PROJECT_ROOT", tmp_path)
    config = TradingConfig(mode="paper")

    with pytest.raises(BrokerError, match="must match starting_cash"):
        PaperTradingEngine(
            config,
            FakePaperClient(equity=101),
            TradingStateStore(config.runtime_directory),
        ).run_once()


def test_bound_state_rejects_a_different_paper_account(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(trading_config_module, "PROJECT_ROOT", tmp_path)
    config = TradingConfig(mode="paper")
    store = TradingStateStore(config.runtime_directory)
    PaperTradingEngine(config, FakePaperClient(), store).run_once()

    with pytest.raises(BrokerError, match="different broker account"):
        PaperTradingEngine(
            config,
            FakePaperClient(account_id="other-paper-account"),
            store,
        ).run_once()


def test_missing_broker_safety_flag_fails_before_planning(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(trading_config_module, "PROJECT_ROOT", tmp_path)
    config = TradingConfig(mode="paper")

    class IncompleteAccountClient(FakePaperClient):
        def get_account(self) -> dict[str, object]:
            value = super().get_account()
            value.pop("trade_suspended_by_user")
            return value

    with pytest.raises(BrokerError, match="requires a boolean"):
        PaperTradingEngine(
            config,
            IncompleteAccountClient(),
            TradingStateStore(config.runtime_directory),
        ).run_once()


def test_missing_position_quantity_fails_closed(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(trading_config_module, "PROJECT_ROOT", tmp_path)
    config = TradingConfig(mode="paper")

    class MalformedPositionClient(FakePaperClient):
        def get_positions(self) -> list[dict[str, object]]:
            return [{"symbol": "SPY", "side": "long"}]

    with pytest.raises(BrokerError, match="missing its quantity"):
        PaperTradingEngine(
            config,
            MalformedPositionClient(),
            TradingStateStore(config.runtime_directory),
        ).run_once()


def test_final_position_refresh_blocks_an_obsolete_buy(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(trading_config_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("RAREIQ_PAPER_ORDER_ACK", PAPER_ACKNOWLEDGEMENT)
    config = TradingConfig(mode="paper")

    class PositionChangedClient(FakePaperClient):
        def __init__(self) -> None:
            super().__init__()
            self.position_calls = 0

        def get_positions(self) -> list[dict[str, object]]:
            self.position_calls += 1
            if self.position_calls >= 3:
                return [{"symbol": "SPY", "qty": "0.05", "side": "long"}]
            return []

    client = PositionChangedClient()
    with pytest.raises(BrokerError, match="direction is no longer required"):
        PaperTradingEngine(
            config, client, TradingStateStore(config.runtime_directory)
        ).run_once(submit_paper_order=True)

    assert client.submit_calls == 0


def test_halted_flat_run_cancels_risk_increasing_order_without_ack(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(trading_config_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("RAREIQ_PAPER_ORDER_ACK", raising=False)
    config = TradingConfig(mode="paper")
    store = TradingStateStore(config.runtime_directory)
    store.save(TradingState(halted=True, halt_reason="daily_loss_halt"))

    class OpenBuyClient(FakePaperClient):
        def __init__(self) -> None:
            super().__init__()
            self.open_buy = True
            self.cancel_calls = 0

        def get_open_orders(self) -> list[dict[str, object]]:
            if not self.open_buy:
                return []
            return [
                {
                    "symbol": "SPY",
                    "side": "buy",
                    "qty": "0.02",
                    "filled_qty": "0",
                }
            ]

        def cancel_all_orders(self) -> list[dict[str, object]]:
            self.cancel_calls += 1
            self.open_buy = False
            return [{"id": "open-buy", "status": 204}]

    client = OpenBuyClient()
    result = PaperTradingEngine(config, client, store).run_once(
        submit_paper_order=True
    )

    assert client.cancel_calls == 1
    assert result["submitted"] is False
    assert result["halt_cancellation"]["remaining_open_orders"] == 0


def test_stopped_order_with_exact_payload_is_committed_not_failed(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(trading_config_module, "PROJECT_ROOT", tmp_path)
    config = TradingConfig(mode="paper")
    plan = OrderPlan(
        symbol="SPY",
        side="buy",
        notional=10,
        quantity=0.02,
        target_value=25,
        current_value=0,
        client_order_id="riq-stopped",
        reason="test",
    )
    payload = paper_order_payload(plan, limit_price=500.25)
    order = {
        **payload,
        "id": "paper-stopped",
        "filled_qty": "0",
        "status": "stopped",
        "order_class": "",
    }
    order.pop("position_intent")

    PaperTradingEngine(
        config,
        FakePaperClient(),
        TradingStateStore(config.runtime_directory),
    )._validate_order_identity(order, payload)


def test_open_order_appearing_during_final_snapshot_blocks_submission(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(trading_config_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("RAREIQ_PAPER_ORDER_ACK", PAPER_ACKNOWLEDGEMENT)
    config = TradingConfig(mode="paper")

    class RacingOrderClient(FakePaperClient):
        def __init__(self) -> None:
            super().__init__()
            self.open_order_calls = 0

        def get_open_orders(self) -> list[dict[str, object]]:
            self.open_order_calls += 1
            if self.open_order_calls >= 3:
                return [{"id": "manual-order", "symbol": "SPY", "side": "buy"}]
            return []

    client = RacingOrderClient()
    with pytest.raises(BrokerError, match="immediately before submission"):
        PaperTradingEngine(
            config, client, TradingStateStore(config.runtime_directory)
        ).run_once(submit_paper_order=True)

    assert client.submit_calls == 0


def test_halted_exit_uses_the_latest_full_position_quantity(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(trading_config_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("RAREIQ_PAPER_ORDER_ACK", PAPER_ACKNOWLEDGEMENT)
    config = TradingConfig(mode="paper")
    store = TradingStateStore(config.runtime_directory)

    class GrowingPositionClient(FakePaperClient):
        def __init__(self) -> None:
            super().__init__()
            self.position_calls = 0

        def get_positions(self) -> list[dict[str, object]]:
            self.position_calls += 1
            quantity = "0.25" if self.position_calls >= 4 else "0.20"
            return [{"symbol": "SPY", "qty": quantity, "side": "long"}]

        def get_daily_bars(self, *_: object, **__: object) -> list[Bar]:
            raise AssertionError("halted emergency exit must not require history")

        def get_asset(self, *_: object, **__: object) -> dict[str, object]:
            raise AssertionError("halted emergency exit must not require asset lookup")

    client = GrowingPositionClient()
    engine = PaperTradingEngine(config, client, store)
    digest = engine._config_digest()
    store.bind_account(
        broker_account_id=client.account_id,
        paper_config_sha256=digest,
        initial_equity=100,
    )
    store.save(
        TradingState(
            halted=True,
            halt_reason="daily_loss_halt",
            metadata={
                "broker_account_id": client.account_id,
                "paper_config_sha256": digest,
                "initial_equity": 100.0,
            },
        )
    )

    result = engine.run_once(submit_paper_order=True)

    assert result["submitted"] is True
    assert client.last_plan is not None
    assert client.last_plan.side == "sell"
    assert client.last_plan.quantity == pytest.approx(0.25)


def test_risk_exit_does_not_cross_the_regular_session_close(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(trading_config_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("RAREIQ_PAPER_ORDER_ACK", PAPER_ACKNOWLEDGEMENT)
    config = TradingConfig(mode="paper")
    store = TradingStateStore(config.runtime_directory)
    near_close = datetime(2026, 8, 27, 19, 59, 59, tzinfo=timezone.utc)

    class ClosingBellClient(FakePaperClient):
        def get_positions(self) -> list[dict[str, object]]:
            return [{"symbol": "SPY", "qty": "0.20", "side": "long"}]

        def get_clock(self) -> dict[str, object]:
            return {
                "timestamp": "2026-08-27T15:59:59-04:00",
                "is_open": True,
                "next_close": "2026-08-27T16:00:00-04:00",
            }

        def get_latest_quote(self, *_: object, **__: object) -> Quote:
            return Quote(timestamp=near_close, bid=499.99, ask=500.01)

    client = ClosingBellClient()
    engine = PaperTradingEngine(config, client, store)
    digest = engine._config_digest()
    store.bind_account(
        broker_account_id=client.account_id,
        paper_config_sha256=digest,
        initial_equity=100,
    )
    store.save(
        TradingState(
            halted=True,
            halt_reason="daily_loss_halt",
            metadata={
                "broker_account_id": client.account_id,
                "paper_config_sha256": digest,
                "initial_equity": 100.0,
            },
        )
    )

    with pytest.raises(BrokerError, match="regular_market_is_closed"):
        engine.run_once(submit_paper_order=True)

    assert client.submit_calls == 0


def test_completed_or_canceled_emergency_exit_can_retry_for_residual_position(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(trading_config_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("RAREIQ_PAPER_ORDER_ACK", PAPER_ACKNOWLEDGEMENT)
    config = TradingConfig(mode="paper")
    store = TradingStateStore(config.runtime_directory)

    class ResidualExitClient(FakePaperClient):
        def __init__(self) -> None:
            super().__init__()
            self.position = 0.20
            self.orders: dict[str, dict[str, object]] = {}
            self.client_ids: list[str] = []

        def get_positions(self) -> list[dict[str, object]]:
            return [
                {
                    "symbol": "SPY",
                    "qty": str(self.position),
                    "side": "long",
                }
            ]

        def get_order_by_client_id(
            self, client_order_id: str
        ) -> dict[str, object] | None:
            self.lookup_calls += 1
            return self.orders.get(client_order_id)

        def submit_marketable_limit_order(
            self, plan: OrderPlan, *, limit_price: float
        ) -> dict[str, object]:
            self.submit_calls += 1
            self.last_plan = plan
            payload = paper_order_payload(plan, limit_price=limit_price)
            order: dict[str, object] = {
                **payload,
                "id": f"filled-{self.submit_calls}",
                "filled_qty": payload["qty"],
                "status": "filled",
            }
            self.orders[plan.client_order_id] = order
            self.client_ids.append(plan.client_order_id)
            return order

    client = ResidualExitClient()
    engine = PaperTradingEngine(config, client, store)
    digest = engine._config_digest()
    store.bind_account(
        broker_account_id=client.account_id,
        paper_config_sha256=digest,
        initial_equity=100,
    )
    store.save(
        TradingState(
            halted=True,
            halt_reason="daily_loss_halt",
            metadata={
                "broker_account_id": client.account_id,
                "paper_config_sha256": digest,
                "initial_equity": 100.0,
            },
        )
    )

    first = engine.run_once(submit_paper_order=True)
    client.position = 0.05
    second = engine.run_once(submit_paper_order=True)
    second_order = client.orders[client.client_ids[1]]
    second_order["status"] = "canceled"
    second_order["filled_qty"] = "0.01"
    client.position = 0.02
    third = engine.run_once(submit_paper_order=True)

    assert first["submitted"] is True
    assert second["submitted"] is True
    assert third["submitted"] is True
    assert client.submit_calls == 3
    assert client.client_ids[0] != client.client_ids[1]
    assert len(set(client.client_ids)) == 3
    assert client.last_plan is not None
    assert client.last_plan.quantity == pytest.approx(0.02)


def test_new_account_loss_halt_uses_exit_path_without_history(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(trading_config_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("RAREIQ_PAPER_ORDER_ACK", PAPER_ACKNOWLEDGEMENT)
    config = TradingConfig(mode="paper")
    store = TradingStateStore(config.runtime_directory)

    class NewlyHaltedClient(FakePaperClient):
        def get_account(self) -> dict[str, object]:
            value = super().get_account()
            value.update({"equity": "99", "last_equity": "100", "cash": "49"})
            return value

        def get_positions(self) -> list[dict[str, object]]:
            return [{"symbol": "SPY", "qty": "0.10", "side": "long"}]

        def get_daily_bars(self, *_: object, **__: object) -> list[Bar]:
            raise AssertionError("a newly detected loss halt must bypass history")

        def get_asset(self, *_: object, **__: object) -> dict[str, object]:
            raise AssertionError("a newly detected loss halt must bypass asset lookup")

    client = NewlyHaltedClient()
    engine = PaperTradingEngine(config, client, store)
    digest = engine._config_digest()
    store.bind_account(
        broker_account_id=client.account_id,
        paper_config_sha256=digest,
        initial_equity=100,
    )
    store.save(
        TradingState(
            high_water_mark=100,
            metadata={
                "broker_account_id": client.account_id,
                "paper_config_sha256": digest,
                "initial_equity": 100.0,
            },
        )
    )

    result = engine.run_once(submit_paper_order=True)

    assert result["submitted"] is True
    assert store.load().halt_reason == "daily_loss_halt"
    assert client.last_plan is not None and client.last_plan.side == "sell"


def test_stale_trailing_history_blocks_paper_order(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(trading_config_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("RAREIQ_PAPER_ORDER_ACK", PAPER_ACKNOWLEDGEMENT)
    config = TradingConfig(mode="paper")

    class StaleHistoryClient(FakePaperClient):
        def get_daily_bars(self, *_: object, **__: object) -> list[Bar]:
            return completed_bars()[:-15]

    client = StaleHistoryClient()
    with pytest.raises(BrokerError, match="too stale"):
        PaperTradingEngine(
            config, client, TradingStateStore(config.runtime_directory)
        ).run_once(submit_paper_order=True)

    assert client.submit_calls == 0
