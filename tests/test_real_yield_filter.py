"""Version 1.1 real-yield filter: no look-ahead, holidays, staleness and direction gating."""

import json
from datetime import date, datetime
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import pytest

from trading.backtest.real_yield import (
    RealYieldFilter,
    RealYieldParameters,
    RealYieldSeries,
    load_series,
)
from trading.models import Direction

NY = ZoneInfo("America/New_York")
PARAMS = RealYieldParameters(lookback=2, threshold=D("0.10"), stale_after_business_days=5)


def series(*values: tuple[str, str], holidays: tuple[str, ...] = ()) -> RealYieldSeries:
    return RealYieldSeries(
        "DFII10",
        "test",
        tuple((date.fromisoformat(d), D(v)) for d, v in values),
        frozenset(date.fromisoformat(h) for h in holidays),
    )


# Wed 4, Thu 5, Fri 6 and Mon 9 Nov 2026; falls 0.20 pp from Wed to Fri.
FALLING = series(("2026-11-04", "2.80"), ("2026-11-05", "2.70"), ("2026-11-06", "2.60"))


def ny(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=NY)


def test_an_observation_is_not_used_before_17_00_new_york_on_the_next_business_day():
    f = RealYieldFilter(FALLING, PARAMS)
    # Friday's value is published on Monday: unusable at 16:59, usable from 17:00.
    assert f.delta(ny(9, 16, 59)) == (None, "real-yield history insufficient")
    assert f.delta(ny(9, 17, 0)) == (D("-0.20"), None)


def test_a_weekday_fred_holiday_delays_publication_to_the_following_business_day():
    s = series(("2026-11-04", "2.80"), ("2026-11-05", "2.70"), ("2026-11-06", "2.60"),
               holidays=("2026-11-09",))  # fmt: skip
    f = RealYieldFilter(s, PARAMS)
    assert f.delta(ny(9, 18))[0] is None
    assert f.delta(ny(10, 17)) == (D("-0.20"), None)


def test_falling_real_yields_allow_longs_only():
    f = RealYieldFilter(FALLING, PARAMS)
    assert f.check(Direction.BUY, ny(10, 10)) is None
    assert f.check(Direction.SELL, ny(10, 10)) == (
        "real-yield filter: entry against the real-yield direction"
    )


def test_rising_real_yields_allow_shorts_only():
    rising = series(("2026-11-04", "2.60"), ("2026-11-05", "2.65"), ("2026-11-06", "2.70"))
    f = RealYieldFilter(rising, PARAMS)
    assert f.check(Direction.SELL, ny(10, 10)) is None
    assert f.check(Direction.BUY, ny(10, 10)) is not None


def test_a_change_inside_the_threshold_is_neutral_and_allows_both_directions():
    flat = series(("2026-11-04", "2.60"), ("2026-11-05", "2.65"), ("2026-11-06", "2.69"))
    f = RealYieldFilter(flat, PARAMS)
    assert f.check(Direction.BUY, ny(10, 10)) is None
    assert f.check(Direction.SELL, ny(10, 10)) is None


def test_stale_real_yield_data_rejects_every_entry():
    f = RealYieldFilter(FALLING, PARAMS)
    # Friday 6 Nov is 6 business days before Monday 16 Nov.
    assert f.check(Direction.BUY, ny(16, 10)) == "real-yield data stale"
    assert f.check(Direction.BUY, ny(13, 10)) is None


def test_fred_download_skips_missing_values_without_filling_them(tmp_path):
    path = tmp_path / "dfii10.json"
    path.write_text(json.dumps({"series_id": "DFII10", "last_updated": "x", "observations": [
        ["2026-11-06", "2.60"], ["2026-11-09", "."], ["2026-11-10", "2.50"]]}))  # fmt: skip
    s = load_series(path)
    assert [d for d, _ in s.values] == [date(2026, 11, 6), date(2026, 11, 10)]
    assert s.holidays == {date(2026, 11, 9)}


def test_the_filter_refuses_a_different_series():
    with pytest.raises(ValueError):
        RealYieldFilter(RealYieldSeries("DGS10", "x", (), frozenset()), PARAMS)
