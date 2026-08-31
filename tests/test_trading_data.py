from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from rareiq.trading.data import validate_bars
from rareiq.trading.models import Bar


def bar(timestamp: datetime) -> Bar:
    return Bar(
        timestamp=timestamp,
        open=100,
        high=102,
        low=99,
        close=101,
        volume=1_000,
    )


def test_daily_bar_validation_accepts_winter_and_summer_eastern_midnight() -> None:
    winter = [bar(datetime(2026, 1, 5, 5, tzinfo=timezone.utc))]
    summer = [bar(datetime(2026, 7, 6, 4, tzinfo=timezone.utc))]

    assert validate_bars(winter) == winter
    assert validate_bars(summer) == summer


def test_daily_bar_validation_rejects_unsorted_input() -> None:
    bars = [
        bar(datetime(2026, 1, 6, 5, tzinfo=timezone.utc)),
        bar(datetime(2026, 1, 5, 5, tzinfo=timezone.utc)),
    ]

    with pytest.raises(ValueError, match="strictly chronological"):
        validate_bars(bars)


def test_daily_bar_validation_rejects_intraday_and_weekend_rows() -> None:
    with pytest.raises(ValueError, match="midnight America/New_York"):
        validate_bars([bar(datetime(2026, 1, 5, 15, tzinfo=timezone.utc))])
    with pytest.raises(ValueError, match="weekend"):
        validate_bars([bar(datetime(2026, 1, 10, 5, tzinfo=timezone.utc))])


def test_bar_requires_an_aware_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        bar(datetime(2026, 1, 5) + timedelta(hours=5))


def test_daily_bar_validation_rejects_sparse_weekly_series() -> None:
    bars = [
        bar(datetime(2026, 1, 5, 5, tzinfo=timezone.utc) + timedelta(days=7 * index))
        for index in range(8)
    ]

    with pytest.raises(ValueError, match="insufficient weekday-session coverage"):
        validate_bars(bars)


def test_daily_bar_validation_rejects_a_long_internal_gap() -> None:
    bars = [
        bar(datetime(2026, 1, 5, 5, tzinfo=timezone.utc)),
        bar(datetime(2026, 1, 13, 5, tzinfo=timezone.utc)),
    ]

    with pytest.raises(ValueError, match="gap longer than seven days"):
        validate_bars(bars)
