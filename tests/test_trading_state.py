from __future__ import annotations

import pytest

from rareiq.trading.models import TradingState
from rareiq.trading.risk import TradingStateStore


def test_state_loader_rejects_nonstandard_nan(tmp_path) -> None:
    store = TradingStateStore(tmp_path)
    store.directory.mkdir(parents=True, exist_ok=True)
    store.state_path.write_text('{"high_water_mark": NaN}', encoding="utf-8")

    with pytest.raises(RuntimeError, match="unreadable"):
        store.load()


def test_stale_writer_cannot_clear_a_concurrent_sticky_halt(tmp_path) -> None:
    store = TradingStateStore(tmp_path)
    stale = store.load()
    halted = TradingState(halted=True, halt_reason="manual_kill_switch")
    store.save(halted)

    stale.high_water_mark = 100
    store.save(stale)
    recovered = store.load()

    assert recovered.halted
    assert recovered.halt_reason == "manual_kill_switch"
    assert recovered.high_water_mark == 100
