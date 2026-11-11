"""Economic calendar and the news restriction for research backtests.

Calendar ingestion (``scripts/build_economic_calendar.py``) is separate from this module and
from signal generation: strategies never read the calendar, the backtest asks ``NewsFilter``
whether an entry moment is allowed.

Rules (strategy candidates, common definitions; programme Amendment 1, A1.4):
- No entries from 30 minutes before to 15 minutes after a covered event.
- An event whose release time is not published blocks the whole New York calendar day.
- Fail closed: if any required event type has no verified coverage for the entry's New York
  date, the entry is rejected ("economic calendar unavailable").
Times are stored as New York wall-clock times and converted with the IANA zone, so US
daylight saving is applied per date.
"""

from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class EconomicEvent:
    kind: str  # e.g. "fomc_statement"
    day: date  # New York date
    release_time: time | None  # New York wall clock; None when the source states no time
    status: str  # "published" (verified on the release itself) or "scheduled"
    source: str  # URL the date and time were verified from

    def moment(self) -> datetime | None:
        if self.release_time is None:
            return None
        return datetime.combine(self.day, self.release_time, tzinfo=NEW_YORK)


@dataclass(frozen=True)
class Coverage:
    kind: str
    start: date  # first New York date for which every event of this kind is listed
    end: date  # last such date
    note: str = ""


@dataclass(frozen=True)
class Calendar:
    events: tuple[EconomicEvent, ...]
    coverage: tuple[Coverage, ...]
    unavailable: dict[str, str]  # kind -> reason it could not be sourced


def load_calendar(path: Path) -> Calendar:
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data.get("timezone") != "America/New_York":
        raise ValueError("calendar times must be America/New_York wall-clock times")
    events = []
    for row in data.get("events", []):
        clock = row.get("time")
        events.append(EconomicEvent(
            kind=row["kind"], day=date.fromisoformat(str(row["date"])),
            release_time=time.fromisoformat(clock) if clock else None,
            status=row["status"], source=row["source"]))  # fmt: skip
    coverage = tuple(
        Coverage(
            c["kind"],
            date.fromisoformat(str(c["from"])),
            date.fromisoformat(str(c["to"])),
            c.get("note", ""),
        )  # fmt: skip
        for c in data.get("coverage", [])
    )
    return Calendar(tuple(events), coverage, dict(data.get("unavailable") or {}))


class NewsFilter:
    def __init__(
        self,
        calendar: Calendar,
        required_kinds: Sequence[str],
        before: timedelta = timedelta(minutes=30),
        after: timedelta = timedelta(minutes=15),
    ) -> None:
        self.required = tuple(required_kinds)
        self.before, self.after = before, after
        self.coverage = {k: [c for c in calendar.coverage if c.kind == k] for k in self.required}
        events = [e for e in calendar.events if e.kind in self.required]
        timed = sorted((m, e) for e in events if (m := e.moment()) is not None)
        self._times = [m for m, _ in timed]
        self._timed = [e for _, e in timed]
        self._whole_days = {(e.day, e.kind) for e in events if e.release_time is None}

    def check(self, moment: datetime) -> str | None:
        """None when an entry at ``moment`` is allowed, otherwise the reason."""
        day = moment.astimezone(NEW_YORK).date()
        for kind in self.required:
            if not any(c.start <= day <= c.end for c in self.coverage[kind]):
                return f"economic calendar unavailable ({kind})"
        # An event at t blocks [t - before, t + after), i.e. t in (m - after, m + before].
        i = bisect_left(self._times, moment - self.after)
        while i < len(self._times) and self._times[i] <= moment + self.before:
            t = self._times[i]
            if t - self.before <= moment < t + self.after:
                return f"news blackout ({self._timed[i].kind} {t.astimezone(NEW_YORK):%H:%M} NY)"
            i += 1
        for kind in self.required:
            if (day, kind) in self._whole_days:
                return f"news blackout ({kind}, release time not published)"
        return None
