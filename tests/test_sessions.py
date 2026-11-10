"""Session-aware judgement of missing time: weekly close, daily breaks, holidays."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from trading.market_data.sessions import load_market_calendar, parse_market_calendar

CALENDAR = load_market_calendar(Path("config/market_sessions.yaml"))


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def calendar_with(closures: list[dict[str, Any]]) -> Any:
    return parse_market_calendar(
        {
            "timezone": "America/New_York",
            "max_unexplained_gap_minutes": 15,
            "profiles": {
                "major_fx": {
                    "symbols": ["EURUSD"],
                    "week_open": {"day": "sunday", "time": "17:00"},
                    "week_close": {"day": "friday", "time": "17:00"},
                },
                "gold": {
                    "symbols": ["XAUUSD"],
                    "week_open": {"day": "sunday", "time": "18:00"},
                    "week_close": {"day": "friday", "time": "17:00"},
                    "daily_breaks": [{"start": "17:00", "end": "18:00"}],
                },
            },
            "closures": closures,
        }
    )


def test_weekend_is_closed_in_winter_and_summer():
    # Fri 17:00 to Sun 17:00 New York: 22:00 UTC in winter (EST), 21:00 UTC in summer (EDT).
    assert CALENDAR.open_time("EURUSD", utc(2026, 11, 6, 22), utc(2026, 11, 8, 22)) == timedelta(0)
    assert CALENDAR.open_time("EURUSD", utc(2026, 7, 10, 21), utc(2026, 7, 12, 21)) == timedelta(0)
    # One hour either side of the weekend is open.
    assert CALENDAR.open_time("EURUSD", utc(2026, 11, 6, 21), utc(2026, 11, 8, 23)) == timedelta(
        hours=2
    )


def test_weekend_spanning_the_us_dst_change_is_closed():
    # Fri 30 Oct 17:00 EDT (21:00 UTC) to Sun 1 Nov 17:00 EST (22:00 UTC).
    assert CALENDAR.open_time("EURUSD", utc(2026, 10, 30, 21), utc(2026, 11, 1, 22)) == timedelta(0)


def test_gold_daily_break_and_later_sunday_open():
    # Mon 16:30 to 18:30 New York: only one hour is open because of the 17:00 to 18:00 break.
    assert CALENDAR.open_time("XAUUSD", utc(2026, 11, 9, 21, 30), utc(2026, 11, 9, 23, 30)) == (
        timedelta(hours=1)
    )
    # Gold opens an hour after forex on Sunday.
    assert CALENDAR.open_time("XAUUSD", utc(2026, 11, 8, 22), utc(2026, 11, 8, 23)) == timedelta(0)
    assert CALENDAR.open_time("EURUSD", utc(2026, 11, 8, 22), utc(2026, 11, 8, 23)) == timedelta(
        hours=1
    )


def test_configured_early_close_is_closed_for_its_profiles_only():
    calendar = calendar_with(
        [
            {
                "profiles": ["gold"],
                "start": "2026-11-26T13:30",
                "end": "2026-11-26T18:00",
                "reason": "early close",
            }
        ]
    )
    window = (utc(2026, 11, 26, 18, 30), utc(2026, 11, 26, 23))  # 13:30 to 18:00 New York
    assert calendar.open_time("XAUUSD", *window) == timedelta(0)
    assert calendar.open_time("EURUSD", *window) == timedelta(hours=4, minutes=30)


def test_full_day_holiday_closure():
    calendar = calendar_with(
        [
            {
                "profiles": ["major_fx", "gold"],
                "start": "2026-12-24T17:00",
                "end": "2026-12-25T17:00",
                "reason": "Christmas",
            }
        ]
    )
    assert calendar.open_time("EURUSD", utc(2026, 12, 24, 22), utc(2026, 12, 25, 22)) == (
        timedelta(0)
    )


def test_unconfigured_symbol_is_rejected():
    with pytest.raises(ValueError, match="no trading session configured for XAUUSD.crp"):
        CALENDAR.open_time("XAUUSD.crp", utc(2026, 11, 9, 10), utc(2026, 11, 9, 11))


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda c: c["profiles"]["gold"]["week_open"].update(time=1080), "quoted 'HH:MM'"),
        (lambda c: c["profiles"]["gold"]["week_open"].update(day="someday"), "weekday name"),
        (lambda c: c["profiles"]["gold"].update(symbols=["EURUSD"]), "already in"),
        (lambda c: c.update(timezone="Mars/Olympus"), "unknown timezone"),
        (lambda c: c.update(max_unexplained_gap_minutes=-1), "integer >= 0"),
        (
            lambda c: c.update(
                closures=[
                    {
                        "profiles": ["silver"],
                        "start": "2026-01-01T00:00",
                        "end": "2026-01-02T00:00",
                        "reason": "x",
                    }
                ]
            ),
            "known profiles",
        ),
        (
            lambda c: c.update(
                closures=[
                    {
                        "profiles": ["gold"],
                        "start": "2026-01-02T00:00",
                        "end": "2026-01-01T00:00",
                        "reason": "x",
                    }
                ]
            ),
            "end must be after start",
        ),
        (
            lambda c: c.update(
                closures=[
                    {"profiles": ["gold"], "start": "2026-01-01T00:00", "end": "2026-01-02T00:00"}
                ]
            ),
            "reason: required",
        ),
    ],
)
def test_invalid_calendar_configuration_is_rejected(change, message):
    config = yaml.safe_load(Path("config/market_sessions.yaml").read_text())
    change(config)
    with pytest.raises(ValueError, match=message):
        parse_market_calendar(config)
