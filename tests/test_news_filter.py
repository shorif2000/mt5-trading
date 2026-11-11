"""News restriction: blackout window, US daylight saving, unpublished times and fail-closed."""

from datetime import UTC, date, datetime, time
from pathlib import Path

from trading.research.news import Calendar, Coverage, EconomicEvent, NewsFilter, load_calendar

FOMC = "fomc_statement"


def calendar(*events: EconomicEvent, start=date(2023, 1, 1), end=date(2026, 12, 31)) -> Calendar:
    return Calendar(events, (Coverage(FOMC, start, end),), {})


def fomc(day: date, clock: time | None = time(14, 0)) -> EconomicEvent:
    return EconomicEvent(FOMC, day, clock, "published" if clock else "scheduled", "test")


def test_blackout_runs_from_30_minutes_before_to_15_minutes_after_in_new_york_time():
    # 2024-09-18 is EDT: 14:00 New York = 18:00 UTC; blackout 17:30 to 18:15 UTC.
    f = NewsFilter(calendar(fomc(date(2024, 9, 18))), [FOMC])
    at = lambda h, m: datetime(2024, 9, 18, h, m, tzinfo=UTC)  # noqa: E731
    assert f.check(at(17, 29)) is None
    assert f.check(at(17, 30)) == "news blackout (fomc_statement 14:00 NY)"
    assert f.check(at(18, 14)) is not None
    assert f.check(at(18, 15)) is None


def test_the_same_new_york_time_moves_in_utc_with_daylight_saving():
    # 2024-12-18 is EST: 14:00 New York = 19:00 UTC, so 18:00 UTC is outside the blackout.
    f = NewsFilter(calendar(fomc(date(2024, 12, 18))), [FOMC])
    assert f.check(datetime(2024, 12, 18, 18, 0, tzinfo=UTC)) is None
    assert f.check(datetime(2024, 12, 18, 18, 45, tzinfo=UTC)) is not None


def test_an_event_without_a_published_time_blocks_its_whole_new_york_day():
    f = NewsFilter(calendar(fomc(date(2026, 12, 9), None)), [FOMC])
    assert f.check(datetime(2026, 12, 9, 14, 0, tzinfo=UTC)) is not None  # 09:00 New York
    # 03:00 UTC on 10 Dec is still 9 Dec in New York (22:00).
    assert f.check(datetime(2026, 12, 10, 3, 0, tzinfo=UTC)) is not None
    assert f.check(datetime(2026, 12, 10, 14, 0, tzinfo=UTC)) is None


def test_entries_outside_verified_coverage_are_rejected():
    f = NewsFilter(calendar(start=date(2024, 1, 1), end=date(2024, 12, 31)), [FOMC])
    assert f.check(datetime(2025, 3, 3, 15, 0, tzinfo=UTC)) == (
        "economic calendar unavailable (fomc_statement)")  # fmt: skip


def test_a_required_event_type_that_was_never_sourced_rejects_every_entry():
    f = NewsFilter(calendar(fomc(date(2024, 9, 18))), [FOMC, "cpi"])
    assert (
        f.check(datetime(2024, 9, 10, 15, 0, tzinfo=UTC)) == "economic calendar unavailable (cpi)"
    )


def test_committed_calendar_uses_official_sources_and_verified_fomc_times():
    cal = load_calendar(Path("config/economic_calendar.yaml"))
    fomc = [e for e in cal.events if e.kind == "fomc_statement" and e.status == "published"]
    assert fomc and all(e.release_time is not None for e in fomc)
    assert all(e.source.startswith(("https://www.federalreserve.gov/", "https://www.bls.gov/"))
               for e in cal.events)  # fmt: skip
    assert not {e.kind for e in cal.events} & cal.unavailable.keys()
