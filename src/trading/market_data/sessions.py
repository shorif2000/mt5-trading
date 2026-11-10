"""Trading sessions and scheduled closures, used to judge gaps and staleness in candle history.

A missing candle is acceptable only if the market was closed: the weekly close, a daily
break, or a configured closure (holiday or early close). The calendar is configuration
(``config/market_sessions.yaml``), not broker data: the bridge does not expose MT5 session
times, so the schedule must be verified against the broker and kept up to date.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

WEEKDAYS = {
    name: index
    for index, name in enumerate(
        ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    )
}


@dataclass(frozen=True)
class WeeklySession:
    open_day: int
    open_time: time
    close_day: int
    close_time: time
    daily_breaks: tuple[tuple[time, time], ...] = ()


@dataclass(frozen=True)
class Closure:
    profiles: frozenset[str]
    start: datetime  # aware
    end: datetime  # aware
    reason: str


@dataclass(frozen=True)
class MarketCalendar:
    zone: ZoneInfo
    profiles: Mapping[str, WeeklySession]
    symbol_profiles: Mapping[str, str]
    closures: tuple[Closure, ...] = ()
    max_unexplained_gap: timedelta = timedelta(minutes=15)

    def open_time(self, symbol: str, start: datetime, end: datetime) -> timedelta:
        """How long the market for ``symbol`` was scheduled to be open in ``[start, end)``."""
        if end <= start:
            return timedelta(0)
        profile = self.symbol_profiles.get(symbol)
        if profile is None:
            raise ValueError(f"no trading session configured for {symbol}")
        overlaps = sorted(
            (max(s, start), min(e, end))
            for s, e in self._closed_intervals(profile, start, end)
            if e > start and s < end
        )
        closed = timedelta(0)
        merged_end: datetime | None = None
        for s, e in overlaps:
            if merged_end is not None and s < merged_end:
                if e > merged_end:
                    closed += e - merged_end
                    merged_end = e
                continue
            closed += e - s
            merged_end = e
        return (end - start) - closed

    def _at(self, day: date, moment: time) -> datetime:
        return datetime.combine(day, moment, tzinfo=self.zone).astimezone(UTC)

    def _closed_intervals(
        self, profile: str, start: datetime, end: datetime
    ) -> list[tuple[datetime, datetime]]:
        session = self.profiles[profile]
        # Start a week early so a weekly close that began before ``start`` is included.
        day = start.astimezone(self.zone).date() - timedelta(days=8)
        last = end.astimezone(self.zone).date() + timedelta(days=1)
        intervals = []
        while day <= last:
            if day.weekday() == session.close_day:
                days_to_open = (session.open_day - session.close_day) % 7 or 7
                intervals.append(
                    (
                        self._at(day, session.close_time),
                        self._at(day + timedelta(days=days_to_open), session.open_time),
                    )
                )
            for break_start, break_end in session.daily_breaks:
                end_day = day if break_end > break_start else day + timedelta(days=1)
                intervals.append((self._at(day, break_start), self._at(end_day, break_end)))
            day += timedelta(days=1)
        intervals.extend((c.start, c.end) for c in self.closures if profile in c.profiles)
        return intervals


# --- loading ----------------------------------------------------------------------------


def _time(value: object, where: str) -> time:
    # Unquoted 17:00 is read by YAML 1.1 as the integer 1020, so only strings are accepted.
    if not isinstance(value, str):
        raise ValueError(f"{where}: time must be a quoted 'HH:MM' string")
    try:
        return time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{where}: invalid time {value!r}") from exc


def _weekday(value: object, where: str) -> int:
    if not isinstance(value, str) or value.lower() not in WEEKDAYS:
        raise ValueError(f"{where}: day must be a weekday name, got {value!r}")
    return WEEKDAYS[value.lower()]


def _moment(value: object, zone: ZoneInfo, where: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{where}: invalid date/time {value!r}") from exc
    else:
        raise ValueError(f"{where}: must be an ISO date/time string")
    # Times without an offset are wall-clock times in the calendar's time zone.
    return parsed.replace(tzinfo=zone) if parsed.tzinfo is None else parsed


def _mapping(value: object, where: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{where}: must be a mapping")
    return value


def parse_market_calendar(data: object) -> MarketCalendar:
    root = _mapping(data, "market calendar")
    zone_name = root.get("timezone")
    if not isinstance(zone_name, str):
        raise ValueError("market calendar: 'timezone' must be an IANA zone name")
    try:
        zone = ZoneInfo(zone_name)
    except (KeyError, ValueError) as exc:
        raise ValueError(f"market calendar: unknown timezone {zone_name!r}") from exc
    gap_minutes = root.get("max_unexplained_gap_minutes")
    if isinstance(gap_minutes, bool) or not isinstance(gap_minutes, int) or gap_minutes < 0:
        raise ValueError("market calendar: 'max_unexplained_gap_minutes' must be an integer >= 0")

    profiles: dict[str, WeeklySession] = {}
    symbol_profiles: dict[str, str] = {}
    for name, raw in _mapping(root.get("profiles"), "profiles").items():
        where = f"profiles.{name}"
        profile = _mapping(raw, where)
        week_open = _mapping(profile.get("week_open"), f"{where}.week_open")
        week_close = _mapping(profile.get("week_close"), f"{where}.week_close")
        breaks = profile.get("daily_breaks") or []
        if not isinstance(breaks, list):
            raise ValueError(f"{where}.daily_breaks: must be a list")
        profiles[name] = WeeklySession(
            open_day=_weekday(week_open.get("day"), f"{where}.week_open.day"),
            open_time=_time(week_open.get("time"), f"{where}.week_open.time"),
            close_day=_weekday(week_close.get("day"), f"{where}.week_close.day"),
            close_time=_time(week_close.get("time"), f"{where}.week_close.time"),
            daily_breaks=tuple(
                (
                    _time(_mapping(b, f"{where}.daily_breaks").get("start"), f"{where}.break"),
                    _time(_mapping(b, f"{where}.daily_breaks").get("end"), f"{where}.break"),
                )
                for b in breaks
            ),
        )
        symbols = profile.get("symbols")
        if not isinstance(symbols, list) or not all(isinstance(s, str) for s in symbols):
            raise ValueError(f"{where}.symbols: must be a list of symbol names")
        for symbol in symbols:
            if symbol in symbol_profiles:
                raise ValueError(f"{where}: {symbol} is already in {symbol_profiles[symbol]}")
            symbol_profiles[symbol] = name

    closures = []
    raw_closures = root.get("closures") or []
    if not isinstance(raw_closures, list):
        raise ValueError("closures: must be a list")
    for index, raw in enumerate(raw_closures):
        where = f"closures[{index}]"
        entry = _mapping(raw, where)
        names = entry.get("profiles")
        if not isinstance(names, list) or not names or not set(names) <= profiles.keys():
            raise ValueError(f"{where}.profiles: must list known profiles {sorted(profiles)}")
        start = _moment(entry.get("start"), zone, f"{where}.start")
        end = _moment(entry.get("end"), zone, f"{where}.end")
        if end <= start:
            raise ValueError(f"{where}: end must be after start")
        reason = entry.get("reason")
        if not isinstance(reason, str) or not reason:
            raise ValueError(f"{where}.reason: required")
        closures.append(Closure(frozenset(names), start, end, reason))

    return MarketCalendar(
        zone=zone,
        profiles=profiles,
        symbol_profiles=symbol_profiles,
        closures=tuple(closures),
        max_unexplained_gap=timedelta(minutes=gap_minutes),
    )


def load_market_calendar(path: Path) -> MarketCalendar:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read market calendar {path}: {exc}") from exc
    return parse_market_calendar(data)
