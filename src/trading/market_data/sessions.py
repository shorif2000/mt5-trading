"""Trading sessions and scheduled closures, used to judge gaps and staleness in candle history.

A missing candle is acceptable only if the market was closed: the weekly close, a daily
break, or a *confirmed* broker closure (full closure, early close or late open). The calendar
is local configuration (``config/market_sessions.yaml``), not broker data: the bridge does not
expose MT5 session times, so the schedule must be verified against the broker.

Exchange holidays (``config/exchange_holidays.yaml``) are loaded as reference information
only. They never explain a gap; they are named in rejection messages, together with any
unconfirmed broker closures, so a reviewer knows what to confirm. Nothing is fetched at
runtime.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from trading.market_data.exchange_holidays import (
    ENTRY_TYPES,
    STATUSES,
    EntryType,
    ExchangeCalendar,
    Status,
    load_exchange_calendar,
)

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
    """A broker session change. ``start``/``end`` bound the closed period: for an early close
    from the early close to the normal reopening, for a late open from the normal opening to
    the late opening."""

    profiles: frozenset[str]
    start: datetime  # aware
    end: datetime  # aware
    reason: str
    type: EntryType = "full_closure"
    status: Status = "confirmed"
    symbols: frozenset[str] = frozenset()
    source: str = ""
    source_url: str | None = None
    retrieved: date | None = None

    def applies_to(self, symbol: str, profile: str) -> bool:
        return profile in self.profiles or symbol in self.symbols


@dataclass(frozen=True)
class MarketCalendar:
    zone: ZoneInfo
    profiles: Mapping[str, WeeklySession]
    symbol_profiles: Mapping[str, str]
    closures: tuple[Closure, ...] = ()
    max_unexplained_gap: timedelta = timedelta(minutes=15)
    reference_markets: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    exchange: ExchangeCalendar | None = None
    last_updated: date | None = None
    closures_reviewed_through: date | None = None

    def notes(self, symbol: str, start: datetime, end: datetime) -> list[str]:
        """Unconfirmed broker closures and reference exchange holidays overlapping
        ``[start, end]``: information for a reviewer, never a reason to accept a gap."""
        profile = self.symbol_profiles.get(symbol, "")
        notes = [
            f"unconfirmed broker {c.type} {c.start.isoformat()} to {c.end.isoformat()}: {c.reason}"
            for c in self.closures
            if c.status == "unconfirmed"
            and c.applies_to(symbol, profile)
            and c.start < end
            and c.end > start
        ]
        if self.exchange is not None:
            for code in self.reference_markets.get(profile, ()):
                market = self.exchange.markets[code]
                first = start.astimezone(market.zone).date()
                last = end.astimezone(market.zone).date()
                notes += [
                    f"exchange reference {code} {market.exchange} {e.day} {e.type}"
                    f"{f' {e.at:%H:%M}' if e.at else ''} {e.name} ({e.status})"
                    for e in market.entries
                    if first <= e.day <= last
                ]
        return notes

    def summary(self) -> list[str]:
        """Last update and coverage, for reports."""
        confirmed = sum(1 for c in self.closures if c.status == "confirmed")
        lines = [
            f"sessions last updated {self.last_updated or 'unknown'}; broker closures reviewed "
            f"through {self.closures_reviewed_through or 'unknown'} "
            f"({confirmed} confirmed, {len(self.closures) - confirmed} unconfirmed)"
        ]
        if self.exchange is not None:
            for code, market in self.exchange.markets.items():
                if market.entries:
                    span = f"{market.entries[0].day} to {market.entries[-1].day}"
                    retrieved = max(e.retrieved for e in market.entries)
                    detail = f"{len(market.entries)} entries {span}, last retrieved {retrieved}"
                else:
                    detail = "no entries"
                mode = "automated" if market.automated else "manual"
                lines.append(f"exchange reference {code} {market.exchange} ({mode}): {detail}")
        return lines

    def open_time(self, symbol: str, start: datetime, end: datetime) -> timedelta:
        """How long the market for ``symbol`` was scheduled to be open in ``[start, end)``."""
        if end <= start:
            return timedelta(0)
        profile = self.symbol_profiles.get(symbol)
        if profile is None:
            raise ValueError(f"no trading session configured for {symbol}")
        overlaps = sorted(
            (max(s, start), min(e, end))
            for s, e in self._closed_intervals(symbol, profile, start, end)
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
        self, symbol: str, profile: str, start: datetime, end: datetime
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
        # Only confirmed closures explain missing time; unconfirmed ones are reported only.
        intervals.extend(
            (c.start, c.end)
            for c in self.closures
            if c.status == "confirmed" and c.applies_to(symbol, profile)
        )
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


def _optional_date(value: object, where: str) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{where}: invalid date {value!r}") from exc
    raise ValueError(f"{where}: must be an ISO date")


def _required_text(entry: Mapping[str, Any], key: str, where: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{where}.{key}: required")
    return value


def _parse_closure(
    raw: object, where: str, zone: ZoneInfo, profiles: Mapping[str, WeeklySession],
    symbols: Mapping[str, str],
) -> Closure:  # fmt: skip
    entry = _mapping(raw, where)
    names = entry.get("profiles") or []
    only = entry.get("symbols") or []
    if not isinstance(names, list) or not set(names) <= profiles.keys():
        raise ValueError(f"{where}.profiles: must list known profiles {sorted(profiles)}")
    if not isinstance(only, list) or not set(only) <= symbols.keys():
        raise ValueError(f"{where}.symbols: must list configured symbols {sorted(symbols)}")
    if not names and not only:
        raise ValueError(f"{where}: set profiles or symbols")
    closure_type = entry.get("type")
    if closure_type not in ENTRY_TYPES:
        raise ValueError(f"{where}.type: must be one of {list(ENTRY_TYPES)}")
    status = entry.get("status")
    if status not in STATUSES:
        raise ValueError(f"{where}.status: must be one of {list(STATUSES)}")
    local_zone = zone
    if entry.get("timezone") is not None:
        try:
            local_zone = ZoneInfo(str(entry["timezone"]))
        except (KeyError, ValueError) as exc:
            raise ValueError(f"{where}.timezone: unknown zone {entry['timezone']!r}") from exc
    start = _moment(entry.get("start"), local_zone, f"{where}.start")
    end = _moment(entry.get("end"), local_zone, f"{where}.end")
    if end <= start:
        raise ValueError(f"{where}: end must be after start")
    reason = _required_text(entry, "reason", where)
    source = _required_text(entry, "source", where)
    source_url = entry.get("source_url")
    if source_url is not None and (not isinstance(source_url, str) or not source_url):
        raise ValueError(f"{where}.source_url: must be text")
    if status == "confirmed" and source_url is None:
        raise ValueError(f"{where}.source_url: required for a confirmed closure (official notice)")
    retrieved = _optional_date(entry.get("retrieved"), f"{where}.retrieved")
    if retrieved is None:
        raise ValueError(f"{where}.retrieved: required")
    return Closure(
        profiles=frozenset(names),
        start=start,
        end=end,
        reason=reason,
        type=closure_type,
        status=status,
        symbols=frozenset(only),
        source=source,
        source_url=source_url,
        retrieved=retrieved,
    )


def _check_overlaps(closures: list[Closure]) -> None:
    """Two confirmed closures for the same profile or symbol must not overlap: that is a
    duplicate or a conflict a reviewer has to resolve."""
    confirmed = sorted((c for c in closures if c.status == "confirmed"), key=lambda c: c.start)
    for index, first in enumerate(confirmed):
        for second in confirmed[index + 1 :]:
            if second.start >= first.end:
                break
            if first.profiles & second.profiles or first.symbols & second.symbols:
                raise ValueError(
                    f"closures overlap or duplicate: {first.reason!r} and {second.reason!r}"
                )


def parse_market_calendar(data: object, exchange: ExchangeCalendar | None = None) -> MarketCalendar:
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

    raw_closures = root.get("closures") or []
    if not isinstance(raw_closures, list):
        raise ValueError("closures: must be a list")
    closures = [
        _parse_closure(raw, f"closures[{i}]", zone, profiles, symbol_profiles)
        for i, raw in enumerate(raw_closures)
    ]
    _check_overlaps(closures)

    reference_markets: dict[str, tuple[str, ...]] = {}
    for name, raw in _mapping(root.get("profiles"), "profiles").items():
        codes = _mapping(raw, f"profiles.{name}").get("reference_markets") or []
        if not isinstance(codes, list):
            raise ValueError(f"profiles.{name}.reference_markets: must be a list")
        if codes and (exchange is None or not set(codes) <= exchange.markets.keys()):
            known = sorted(exchange.markets) if exchange else []
            raise ValueError(f"profiles.{name}.reference_markets: must be among {known}")
        reference_markets[name] = tuple(codes)

    return MarketCalendar(
        zone=zone,
        profiles=profiles,
        symbol_profiles=symbol_profiles,
        closures=tuple(closures),
        max_unexplained_gap=timedelta(minutes=gap_minutes),
        reference_markets=reference_markets,
        exchange=exchange,
        last_updated=_optional_date(root.get("last_updated"), "last_updated"),
        closures_reviewed_through=_optional_date(
            root.get("closures_reviewed_through"), "closures_reviewed_through"
        ),
    )


def load_market_calendar(path: Path) -> MarketCalendar:
    """Load the local sessions file and the exchange reference file it names. Both are local;
    a missing or invalid file is an error, never silently replaced by an empty calendar."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read market calendar {path}: {exc}") from exc
    name = _mapping(data, "market calendar").get("exchange_calendar")
    if not isinstance(name, str) or not name:
        raise ValueError("market calendar: 'exchange_calendar' must name the reference file")
    return parse_market_calendar(data, load_exchange_calendar(path.parent / name))
