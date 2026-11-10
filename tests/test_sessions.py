"""Session-aware judgement of missing time: weekly close, daily breaks and broker closures."""

import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from trading.market_data.exchange_holidays import parse_exchange_calendar
from trading.market_data.sessions import load_market_calendar, parse_market_calendar

CALENDAR = load_market_calendar(Path("config/market_sessions.yaml"))
REFERENCE = parse_exchange_calendar(
    {
        "markets": {
            "US": {
                "exchange": "NYSE",
                "timezone": "America/New_York",
                "source": "NYSE",
                "source_url": "https://example.test/nyse",
                "automated": True,
                "entries": [
                    {"date": "2026-11-26", "type": "full_closure", "name": "Thanksgiving Day",
                     "status": "confirmed", "retrieved": "2026-11-01"},
                ],
            }
        }
    }
)  # fmt: skip


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def closure(**overrides: Any) -> dict[str, Any]:
    entry = {
        "type": "full_closure",
        "profiles": ["gold"],
        "start": "2026-11-26T13:30",
        "end": "2026-11-26T18:00",
        "reason": "test closure",
        "source": "Broker trading notice",
        "source_url": "https://example.test/notice",
        "retrieved": "2026-11-01",
        "status": "confirmed",
    }
    entry.update(overrides)
    return {k: v for k, v in entry.items() if v is not None}


def calendar_with(closures: list[dict[str, Any]], exchange: Any = None) -> Any:
    return parse_market_calendar(
        {
            "timezone": "America/New_York",
            "max_unexplained_gap_minutes": 15,
            "profiles": {
                "major_fx": {
                    "symbols": ["EURUSD", "GBPUSD"],
                    "week_open": {"day": "sunday", "time": "17:00"},
                    "week_close": {"day": "friday", "time": "17:00"},
                    "reference_markets": ["US"] if exchange else [],
                },
                "gold": {
                    "symbols": ["XAUUSD"],
                    "week_open": {"day": "sunday", "time": "18:00"},
                    "week_close": {"day": "friday", "time": "17:00"},
                    "daily_breaks": [{"start": "17:00", "end": "18:00"}],
                    "reference_markets": ["US"] if exchange else [],
                },
            },
            "closures": closures,
        },
        exchange,
    )


THANKSGIVING_AFTERNOON = (utc(2026, 11, 26, 18, 30), utc(2026, 11, 26, 23))  # 13:30-18:00 NY


# --- weekly sessions --------------------------------------------------------------------


def test_weekend_is_closed_in_winter_and_summer():
    # Fri 17:00 to Sun 17:00 New York: 22:00 UTC in winter (EST), 21:00 UTC in summer (EDT).
    assert CALENDAR.open_time("EURUSD", utc(2026, 11, 6, 22), utc(2026, 11, 8, 22)) == timedelta(0)
    assert CALENDAR.open_time("EURUSD", utc(2026, 7, 10, 21), utc(2026, 7, 12, 21)) == timedelta(0)
    assert CALENDAR.open_time("EURUSD", utc(2026, 11, 6, 21), utc(2026, 11, 8, 23)) == timedelta(
        hours=2
    )


def test_weekend_spanning_the_us_dst_change_is_closed():
    assert CALENDAR.open_time("EURUSD", utc(2026, 10, 30, 21), utc(2026, 11, 1, 22)) == timedelta(0)


def test_gold_daily_break_and_later_sunday_open():
    assert CALENDAR.open_time("XAUUSD", utc(2026, 11, 9, 21, 30), utc(2026, 11, 9, 23, 30)) == (
        timedelta(hours=1)
    )
    assert CALENDAR.open_time("XAUUSD", utc(2026, 11, 8, 22), utc(2026, 11, 8, 23)) == timedelta(0)


def test_unconfigured_symbol_is_rejected():
    with pytest.raises(ValueError, match="no trading session configured for XAUUSD.crp"):
        CALENDAR.open_time("XAUUSD.crp", utc(2026, 11, 9, 10), utc(2026, 11, 9, 11))


# --- broker closures --------------------------------------------------------------------


def test_confirmed_early_close_is_closed_for_its_profile_only():
    calendar = calendar_with([closure(type="early_close")])
    assert calendar.open_time("XAUUSD", *THANKSGIVING_AFTERNOON) == timedelta(0)
    assert calendar.open_time("EURUSD", *THANKSGIVING_AFTERNOON) == timedelta(hours=4, minutes=30)


def test_full_day_closure():
    calendar = calendar_with(
        [closure(profiles=["major_fx", "gold"], start="2026-12-24T17:00", end="2026-12-25T17:00")]
    )
    assert calendar.open_time("EURUSD", utc(2026, 12, 24, 22), utc(2026, 12, 25, 22)) == (
        timedelta(0)
    )


def test_late_open_covers_only_the_delayed_start():
    # Normal Sunday open 17:00 New York, delayed to 19:00.
    calendar = calendar_with(
        [closure(type="late_open", profiles=["major_fx"], start="2026-11-08T17:00",
                 end="2026-11-08T19:00")]
    )  # fmt: skip
    assert calendar.open_time("EURUSD", utc(2026, 11, 8, 22), utc(2026, 11, 9, 1)) == timedelta(
        hours=1
    )


def test_instrument_specific_closure_does_not_affect_other_symbols_in_the_profile():
    calendar = calendar_with([closure(profiles=None, symbols=["GBPUSD"])])
    assert calendar.open_time("GBPUSD", *THANKSGIVING_AFTERNOON) == timedelta(0)
    assert calendar.open_time("EURUSD", *THANKSGIVING_AFTERNOON) == timedelta(hours=4, minutes=30)


def test_closure_in_its_own_market_time_zone():
    # 12:30 to 17:00 London on 24 Dec 2026 is 12:30 to 17:00 UTC (GMT).
    calendar = calendar_with(
        [closure(profiles=["major_fx"], timezone="Europe/London", start="2026-12-24T12:30",
                 end="2026-12-24T17:00")]
    )  # fmt: skip
    assert calendar.open_time("EURUSD", utc(2026, 12, 24, 12, 30), utc(2026, 12, 24, 17)) == (
        timedelta(0)
    )
    assert calendar.open_time("EURUSD", utc(2026, 12, 24, 12), utc(2026, 12, 24, 12, 30)) == (
        timedelta(minutes=30)
    )


def test_unconfirmed_closure_never_explains_a_gap_but_is_reported():
    calendar = calendar_with([closure(status="unconfirmed", reason="possible early close")])
    # 13:30-18:00 New York minus gold's 17:00-18:00 daily break: 3.5 open hours remain.
    assert calendar.open_time("XAUUSD", *THANKSGIVING_AFTERNOON) == timedelta(hours=3, minutes=30)
    notes = calendar.notes("XAUUSD", *THANKSGIVING_AFTERNOON)
    assert len(notes) == 1 and "unconfirmed broker full_closure" in notes[0]


def test_exchange_holiday_is_reference_only():
    calendar = calendar_with([], exchange=REFERENCE)
    # The NYSE holiday does not close the broker's gold session...
    # 13:30-18:00 New York minus gold's 17:00-18:00 daily break: 3.5 open hours remain.
    assert calendar.open_time("XAUUSD", *THANKSGIVING_AFTERNOON) == timedelta(hours=3, minutes=30)
    # ...but is named for the reviewer.
    assert calendar.notes("XAUUSD", *THANKSGIVING_AFTERNOON) == [
        "exchange reference US NYSE 2026-11-26 full_closure Thanksgiving Day (confirmed)"
    ]


def test_duplicate_confirmed_closures_are_rejected():
    with pytest.raises(ValueError, match="overlap or duplicate"):
        calendar_with([closure(reason="first"), closure(reason="second")])


def test_conflicting_overlapping_confirmed_closures_are_rejected():
    with pytest.raises(ValueError, match="overlap or duplicate"):
        calendar_with(
            [
                closure(),
                closure(type="early_close", start="2026-11-26T15:00", end="2026-11-26T18:00"),
            ]
        )


def test_unconfirmed_entry_may_overlap_a_confirmed_one():
    calendar_with([closure(), closure(status="unconfirmed")])  # does not raise


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"type": "half_day"}, "type: must be one of"),
        ({"status": "probably"}, "status: must be one of"),
        ({"source": None}, "source: required"),
        ({"source_url": None}, "source_url: required for a confirmed closure"),
        ({"retrieved": None}, "retrieved: required"),
        ({"reason": None}, "reason: required"),
        ({"profiles": None}, "set profiles or symbols"),
        ({"profiles": ["silver"]}, "known profiles"),
        ({"symbols": ["XAUUSD.crp"]}, "configured symbols"),
        ({"timezone": "Mars/Olympus"}, "unknown zone"),
        ({"end": "2026-11-26T13:00"}, "end must be after start"),
        ({"start": "26/11/2026"}, "invalid date/time"),
    ],
)
def test_invalid_closure_is_rejected(overrides, message):
    with pytest.raises(ValueError, match=message):
        calendar_with([closure(**overrides)])


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda c: c["profiles"]["gold"]["week_open"].update(time=1080), "quoted 'HH:MM'"),
        (lambda c: c["profiles"]["gold"]["week_open"].update(day="someday"), "weekday name"),
        (lambda c: c["profiles"]["gold"].update(symbols=["EURUSD"]), "already in"),
        (lambda c: c.update(timezone="Mars/Olympus"), "unknown timezone"),
        (lambda c: c["profiles"]["gold"].update(reference_markets=["MARS"]), "must be among"),
    ],
)
def test_invalid_session_configuration_is_rejected(change, message):
    config = yaml.safe_load(Path("config/market_sessions.yaml").read_text())
    change(config)
    with pytest.raises(ValueError, match=message):
        parse_market_calendar(config, CALENDAR.exchange)


# --- local operation --------------------------------------------------------------------


def test_calendar_loads_and_reports_coverage_without_network(monkeypatch):
    def no_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    calendar = load_market_calendar(Path("config/market_sessions.yaml"))

    summary = calendar.summary()
    assert summary[0].startswith("sessions last updated 2026-11-10")
    assert any(line.startswith("exchange reference US NYSE (automated)") for line in summary)
    assert any("JP JPX (manual)" in line for line in summary)


def test_missing_exchange_file_is_an_error_not_an_empty_calendar(tmp_path):
    sessions = tmp_path / "market_sessions.yaml"
    sessions.write_text(Path("config/market_sessions.yaml").read_text())
    with pytest.raises(ValueError, match="cannot read exchange calendar"):
        load_market_calendar(sessions)


# --- repository placeholders for unconfirmed holiday dates ------------------------------


@pytest.mark.parametrize(
    ("symbol", "window", "label"),
    [
        ("XAUUSD", (utc(2026, 11, 26, 14), utc(2026, 11, 26, 20)), "US Thanksgiving: XAUUSD"),
        ("EURUSD", (utc(2026, 12, 25, 6), utc(2026, 12, 25, 12)), "Christmas Day: forex"),
        ("GBPUSD", (utc(2027, 1, 1, 6), utc(2027, 1, 1, 12)), "New Year's Day: forex"),
    ],
)
def test_unconfirmed_holiday_dates_are_flagged_but_never_explain_a_gap(symbol, window, label):
    open_without_placeholders = calendar_with([]).open_time(symbol, *window)
    # The placeholders do not close the market...
    assert CALENDAR.open_time(symbol, *window) == open_without_placeholders > timedelta(0)
    # ...but a gap on that date names them, scoped to the right instrument group only.
    notes = [n for n in CALENDAR.notes(symbol, *window) if n.startswith("unconfirmed")]
    assert len(notes) == 1 and label in notes[0]


def test_unconfirmed_placement_does_not_mix_gold_and_forex():
    window = (utc(2026, 11, 26, 14), utc(2026, 11, 26, 20))
    gold = " ".join(CALENDAR.notes("XAUUSD", *window))
    forex = " ".join(CALENDAR.notes("EURUSD", *window))
    assert "XAUUSD schedule" in gold and "forex schedule" not in gold
    assert "forex schedule" in forex and "XAUUSD schedule" not in forex
