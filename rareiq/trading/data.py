from __future__ import annotations

import csv
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Iterable

from rareiq.trading.models import Bar


REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")


def _first_sunday(year: int, month: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(6 - first.weekday()) % 7)


def _eastern_utc_offset(session_date: date) -> int:
    """Return the post-2007 US Eastern offset for a market session date."""

    daylight_start = _first_sunday(session_date.year, 3) + timedelta(days=7)
    standard_start = _first_sunday(session_date.year, 11)
    return -4 if daylight_start < session_date < standard_start else -5


def _eastern_session_date(timestamp: datetime) -> date | None:
    instant = timestamp.astimezone(timezone.utc)
    for offset in (-4, -5):
        local = instant + timedelta(hours=offset)
        if (
            local.time().replace(tzinfo=None) == time.min
            and _eastern_utc_offset(local.date()) == offset
        ):
            return local.date()
    return None


def parse_timestamp(value: str) -> datetime:
    normalized = str(value).strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"invalid bar timestamp: {value!r}") from exc


def validate_bars(bars: Iterable[Bar]) -> list[Bar]:
    ordered = list(bars)
    if not ordered:
        raise ValueError("no market bars were supplied")
    timestamps = [item.timestamp for item in ordered]
    if any(item.tzinfo is None or item.utcoffset() is None for item in timestamps):
        raise ValueError("daily market bars require timezone-aware timestamps")
    instants = [item.astimezone(timezone.utc) for item in timestamps]
    if any(current <= previous for previous, current in zip(instants, instants[1:])):
        raise ValueError("daily market bars must be strictly chronological")
    session_dates = [_eastern_session_date(item) for item in timestamps]
    if any(item is None for item in session_dates):
        raise ValueError("daily market bars must be stamped at midnight America/New_York")
    if len(set(session_dates)) != len(session_dates):
        raise ValueError("daily market bars contain more than one bar per session date")
    if any(item is not None and item.weekday() >= 5 for item in session_dates):
        raise ValueError("daily market bars cannot use weekend session dates")
    if any(
        (current - previous).days > 7
        for previous, current in zip(session_dates, session_dates[1:])
        if previous is not None and current is not None
    ):
        raise ValueError("daily market bars contain a session gap longer than seven days")
    first_session = session_dates[0]
    last_session = session_dates[-1]
    assert first_session is not None and last_session is not None
    span_days = (last_session - first_session).days + 1
    expected_weekdays = sum(
        1
        for offset in range(span_days)
        if (first_session + timedelta(days=offset)).weekday() < 5
    )
    coverage = len(session_dates) / expected_weekdays
    if coverage < 0.94:
        raise ValueError("daily market bars have insufficient weekday-session coverage")
    return ordered


def load_bars_csv(path: str | Path) -> list[Bar]:
    csv_path = Path(path)
    try:
        handle = csv_path.open("r", encoding="utf-8-sig", newline="")
    except FileNotFoundError as exc:
        raise ValueError(f"bar CSV not found: {csv_path}") from exc
    with handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or ())
        missing = [name for name in REQUIRED_COLUMNS if name not in fields]
        if missing:
            raise ValueError(f"bar CSV is missing columns: {', '.join(missing)}")
        bars = [
            Bar(
                timestamp=parse_timestamp(row["timestamp"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
            for row in reader
        ]
    return validate_bars(bars)


def save_bars_csv(path: str | Path, bars: Iterable[Bar]) -> Path:
    csv_path = Path(path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    ordered = validate_bars(bars)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(REQUIRED_COLUMNS))
        writer.writeheader()
        for bar in ordered:
            writer.writerow(
                {
                    "timestamp": bar.timestamp.isoformat(),
                    "open": f"{bar.open:.8f}",
                    "high": f"{bar.high:.8f}",
                    "low": f"{bar.low:.8f}",
                    "close": f"{bar.close:.8f}",
                    "volume": f"{bar.volume:.4f}",
                }
            )
    return csv_path
