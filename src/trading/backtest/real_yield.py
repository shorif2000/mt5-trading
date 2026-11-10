"""Version 1.1 real-yield direction filter (docs/strategy-xauusd-v1.1-real-yield-filter.md).

Gates new entries by the change in FRED DFII10 (10-year TIPS yield) over the last
``lookback`` published observations, using only observations available at the decision time:
the observation for date D is used from 17:00 New York on the next US business day after D
(H.15 is published on that day at about 16:15 New York). FRED marks days without a value with
"." (weekday holidays); they are skipped, never filled, and are not business days here.
"""

import json
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from trading.models import Direction

NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class RealYieldParameters:
    """Approved Version 1.1 defaults (owner decision 2026-11-10), fixed before any result."""

    series_id: str = "DFII10"
    lookback: int = 20  # published observations (business days)
    threshold: Decimal = Decimal("0.10")  # percentage points (10 basis points)
    neutral_allows_both: bool = True
    stale_after_business_days: int = 5
    available_from: time = time(17, 0)  # New York, on the next business day after D


@dataclass(frozen=True)
class RealYieldSeries:
    series_id: str
    last_updated: str
    values: tuple[tuple[date, Decimal], ...]  # published values only, ascending
    holidays: frozenset[date]  # weekdays FRED marks "." (no publication)


def load_series(path: Path) -> RealYieldSeries:
    """A FRED observations download (JSON, as returned by the FRED MCP download link)."""
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    values, holidays = [], set()
    for day_text, value in raw["observations"]:
        day = date.fromisoformat(day_text)
        if value == ".":
            holidays.add(day)
        else:
            values.append((day, Decimal(value)))
    values.sort()
    return RealYieldSeries(
        raw["series_id"], raw["last_updated"], tuple(values), frozenset(holidays)
    )


class RealYieldFilter:
    def __init__(self, series: RealYieldSeries, params: RealYieldParameters | None = None) -> None:
        self.params = params or RealYieldParameters()
        if series.series_id != self.params.series_id:
            raise ValueError(f"expected {self.params.series_id}, got {series.series_id}")
        self.series = series
        self.values = series.values
        self.available = [self._available_at(day) for day, _ in series.values]

    def _is_business_day(self, day: date) -> bool:
        return day.weekday() < 5 and day not in self.series.holidays

    def _next_business_day(self, day: date) -> date:
        day += timedelta(days=1)
        while not self._is_business_day(day):
            day += timedelta(days=1)
        return day

    def _available_at(self, day: date) -> datetime:
        publication = self._next_business_day(day)
        return datetime.combine(publication, self.params.available_from, tzinfo=NEW_YORK)

    def _business_days_between(self, start: date, end: date) -> int:
        count, day = 0, start
        while day < end:
            day += timedelta(days=1)
            if self._is_business_day(day):
                count += 1
        return count

    def delta(self, moment: datetime) -> tuple[Decimal | None, str | None]:
        """The real-yield change known at ``moment``, or a reason it is unavailable."""
        latest = bisect_right(self.available, moment) - 1
        if latest < 0:
            return None, "real-yield data unavailable"
        day = self.values[latest][0]
        if (
            self._business_days_between(day, moment.astimezone(NEW_YORK).date())
            > self.params.stale_after_business_days
        ):
            return None, "real-yield data stale"
        if latest < self.params.lookback:
            return None, "real-yield history insufficient"
        return self.values[latest][1] - self.values[latest - self.params.lookback][1], None

    def check(self, direction: Direction, moment: datetime) -> str | None:
        """None when an entry in ``direction`` is allowed at ``moment``, else the reason."""
        delta, problem = self.delta(moment)
        if delta is None:
            return problem
        if delta <= -self.params.threshold:
            allowed: Sequence[Direction] = (Direction.BUY,)
        elif delta >= self.params.threshold:
            allowed = (Direction.SELL,)
        else:
            allowed = (Direction.BUY, Direction.SELL) if self.params.neutral_allows_both else ()
        if direction in allowed:
            return None
        return f"real-yield filter: {delta:+.2f} pp over {self.params.lookback} days"
