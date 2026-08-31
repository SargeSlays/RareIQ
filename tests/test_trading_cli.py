from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import rareiq.trading.config as trading_config_module
import rareiq.trading.cli as trading_cli_module
from rareiq.trading.cli import _config_hash, main
from rareiq.trading.config import TradingConfig
from rareiq.trading.data import save_bars_csv
from rareiq.trading.broker import BrokerError
from rareiq.trading.risk import TradingStateStore
from tests.test_trading_strategy import bars_with_growth


def write_config(path, config: TradingConfig) -> None:
    path.write_text(
        json.dumps(config.as_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_kill_switch_latches_without_credentials(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(trading_config_module, "PROJECT_ROOT", tmp_path)
    for name in (
        "APCA_API_KEY_ID",
        "APCA_API_SECRET_KEY",
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    config = TradingConfig()
    config_path = tmp_path / "config.json"
    write_config(config_path, config)

    exit_code = main(["kill-switch", "--config", str(config_path)])

    state = TradingStateStore(config.runtime_directory).load()
    assert exit_code == 2
    assert state.halted
    assert state.halt_reason == "manual_kill_switch"


def test_backtest_requires_hash_bound_symbol_provenance(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(trading_config_module, "PROJECT_ROOT", tmp_path)
    config = TradingConfig()
    config_path = tmp_path / "config.json"
    write_config(config_path, config)
    bars = bars_with_growth(240)
    csv_path = save_bars_csv(tmp_path / "bars.csv", bars)

    missing_exit = main(
        ["backtest", "--config", str(config_path), "--csv", str(csv_path)]
    )
    assert missing_exit == 2

    metadata_path = tmp_path / "bars.csv.meta.json"
    metadata = {
        "schema_version": 1,
        "source": "alpaca_market_data_api",
        "symbol": "QQQ",
        "feed": "iex",
        "timeframe": "1Day",
        "adjustment": "all",
        "requested_start": bars[0].timestamp.isoformat(),
        "requested_end": bars[-1].timestamp.isoformat(),
        "first_bar": bars[0].timestamp.isoformat(),
        "last_bar": bars[-1].timestamp.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "bar_count": 240,
        "csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
    }
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    wrong_symbol_exit = main(
        ["backtest", "--config", str(config_path), "--csv", str(csv_path)]
    )

    assert wrong_symbol_exit == 2

    metadata["symbol"] = "SPY"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    report_path = tmp_path / "report.json"
    success_exit = main(
        [
            "backtest",
            "--config",
            str(config_path),
            "--csv",
            str(csv_path),
            "--report",
            str(report_path),
        ]
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert success_exit == 0
    assert report["input"]["provenance"]["symbol"] == "SPY"
    assert report["input"]["config"] == config.as_dict()
    assert len(report["input"]["implementation_sha256"]) == 64
    assert report["preliminary_full_sample_diagnostics"][
        "promotion_gate_evaluated"
    ] is False


class FakeKillClient:
    def __init__(self, account_id: str) -> None:
        self.account_id = account_id
        self.cancel_calls = 0

    def __enter__(self) -> "FakeKillClient":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def get_account(self) -> dict[str, object]:
        return {"id": self.account_id}

    def cancel_all_orders(self) -> list[dict[str, object]]:
        self.cancel_calls += 1
        return [{"id": "paper-order", "status": 204}]

    def get_open_orders(self) -> list[dict[str, object]]:
        return []

    def get_positions(self) -> list[dict[str, object]]:
        return []


def test_kill_switch_uses_binding_even_when_config_and_state_are_corrupt(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(trading_config_module, "PROJECT_ROOT", tmp_path)
    config = TradingConfig()
    store = TradingStateStore(config.runtime_directory)
    store.bind_account(
        broker_account_id="bound-paper-account",
        paper_config_sha256=_config_hash(config),
        initial_equity=100,
    )
    store.state_path.write_text("{corrupt", encoding="utf-8")
    config_path = tmp_path / "broken-config.json"
    config_path.write_text("{corrupt", encoding="utf-8")
    fake = FakeKillClient("bound-paper-account")
    monkeypatch.setattr(trading_cli_module, "AlpacaPaperClient", lambda _: fake)
    monkeypatch.setenv("APCA_API_KEY_ID", "paper-key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "paper-secret")

    exit_code = main(["kill-switch", "--config", str(config_path)])

    assert exit_code == 0
    assert fake.cancel_calls == 2
    assert store.kill_switch_latched()


def test_kill_switch_refuses_to_cancel_a_different_credential_account(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(trading_config_module, "PROJECT_ROOT", tmp_path)
    config = TradingConfig()
    store = TradingStateStore(config.runtime_directory)
    store.bind_account(
        broker_account_id="bound-paper-account",
        paper_config_sha256=_config_hash(config),
        initial_equity=100,
    )
    config_path = tmp_path / "config.json"
    write_config(config_path, config)
    fake = FakeKillClient("other-paper-account")
    monkeypatch.setattr(trading_cli_module, "AlpacaPaperClient", lambda _: fake)
    monkeypatch.setenv("APCA_API_KEY_ID", "paper-key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "paper-secret")

    exit_code = main(["kill-switch", "--config", str(config_path)])

    assert exit_code == 2
    assert fake.cancel_calls == 0
    assert store.kill_switch_latched()


def test_kill_switch_retries_under_lock_after_immediate_cancel_failure(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(trading_config_module, "PROJECT_ROOT", tmp_path)
    config = TradingConfig()
    store = TradingStateStore(config.runtime_directory)
    store.bind_account(
        broker_account_id="bound-paper-account",
        paper_config_sha256=_config_hash(config),
        initial_equity=100,
    )
    config_path = tmp_path / "config.json"
    write_config(config_path, config)

    class TransientCancelClient(FakeKillClient):
        def cancel_all_orders(self) -> list[dict[str, object]]:
            self.cancel_calls += 1
            if self.cancel_calls == 1:
                raise BrokerError("transient cancel failure")
            return []

    fake = TransientCancelClient("bound-paper-account")
    monkeypatch.setattr(trading_cli_module, "AlpacaPaperClient", lambda _: fake)
    monkeypatch.setenv("APCA_API_KEY_ID", "paper-key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "paper-secret")

    exit_code = main(["kill-switch", "--config", str(config_path)])

    assert exit_code == 0
    assert fake.cancel_calls == 2
