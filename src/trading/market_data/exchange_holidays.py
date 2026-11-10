"""Exchange holiday reference calendar: data model, official-source parsers and the updater.

``config/exchange_holidays.yaml`` holds exchange holidays as *reference information*. They are
not MT5 broker closures: the broker's forex and gold sessions do not follow any one exchange.
Only confirmed closures in ``market_sessions.yaml`` explain gaps in candle history.

The updater (``mt5-calendar-update``) is independent of the application. It fetches the
official exchange pages that can be parsed reliably, normalises them, compares the result with
the local file and writes a report. It never removes or overwrites an existing entry: a
conflict or a source failure leaves that market's entries untouched, so the last known good
calendar is preserved. The application only ever reads the local file.
"""

import argparse
import html
import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import truststore
import yaml

EntryType = Literal["full_closure", "early_close", "late_open"]
Status = Literal["confirmed", "unconfirmed"]
ENTRY_TYPES: tuple[EntryType, ...] = ("full_closure", "early_close", "late_open")
STATUSES: tuple[Status, ...] = ("confirmed", "unconfirmed")
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
MONTHS = {
    name: index
    for index, name in enumerate(
        (
            "january", "february", "march", "april", "may", "june",
            "july", "august", "september", "october", "november", "december",
        ),
        start=1,
    )
}  # fmt: skip
FETCH_TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 5_000_000
USER_AGENT = "mt5-trading-calendar-updater/1.0"


class SourceError(Exception):
    """A source could not be fetched, or its content was missing, invalid or ambiguous."""


@dataclass(frozen=True)
class HolidayEntry:
    day: date
    type: EntryType
    name: str
    status: Status
    retrieved: date
    at: time | None = None  # close time for early_close, open time for late_open
    note: str | None = None
    source_url: str | None = None  # only when it differs from the market's source

    def key(self) -> tuple[date, str]:
        return (self.day, self.type)

    def same_content(self, other: "HolidayEntry") -> bool:
        return (self.day, self.type, self.at, self.name) == (
            other.day,
            other.type,
            other.at,
            other.name,
        )


@dataclass(frozen=True)
class MarketHolidays:
    code: str
    exchange: str
    timezone: str
    source: str
    source_url: str
    automated: bool
    entries: tuple[HolidayEntry, ...] = ()

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@dataclass(frozen=True)
class ExchangeCalendar:
    markets: Mapping[str, MarketHolidays]


# --- validation of the local file (used at runtime) -------------------------------------


def _mapping(value: object, where: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{where}: must be a mapping")
    return value


def _text(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}: required text")
    return value


def _date(value: object, where: str) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{where}: invalid date {value!r}") from exc
    raise ValueError(f"{where}: must be an ISO date")


def _time(value: object, where: str) -> time:
    if not isinstance(value, str):
        raise ValueError(f"{where}: time must be a quoted 'HH:MM' string")
    try:
        return time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{where}: invalid time {value!r}") from exc


def parse_entry(raw: object, where: str) -> HolidayEntry:
    item = _mapping(raw, where)
    entry_type = item.get("type")
    if entry_type not in ENTRY_TYPES:
        raise ValueError(f"{where}.type: must be one of {list(ENTRY_TYPES)}")
    status = item.get("status")
    if status not in STATUSES:
        raise ValueError(f"{where}.status: must be one of {list(STATUSES)}")
    moment = item.get("time")
    if entry_type == "full_closure":
        if moment is not None:
            raise ValueError(f"{where}: a full_closure has no time")
        parsed_time = None
    else:
        parsed_time = _time(moment, f"{where}.time")
    note = item.get("note")
    source_url = item.get("source_url")
    return HolidayEntry(
        day=_date(item.get("date"), f"{where}.date"),
        type=entry_type,
        name=_text(item.get("name"), f"{where}.name"),
        status=status,
        retrieved=_date(item.get("retrieved"), f"{where}.retrieved"),
        at=parsed_time,
        note=_text(note, f"{where}.note") if note is not None else None,
        source_url=_text(source_url, f"{where}.source_url") if source_url is not None else None,
    )


def parse_exchange_calendar(data: object) -> ExchangeCalendar:
    root = _mapping(data, "exchange calendar")
    markets = {}
    for code, raw in _mapping(root.get("markets"), "exchange calendar.markets").items():
        where = f"markets.{code}"
        market = _mapping(raw, where)
        zone_name = _text(market.get("timezone"), f"{where}.timezone")
        try:
            ZoneInfo(zone_name)
        except (KeyError, ValueError) as exc:
            raise ValueError(f"{where}.timezone: unknown zone {zone_name!r}") from exc
        automated = market.get("automated")
        if not isinstance(automated, bool):
            raise ValueError(f"{where}.automated: must be true or false")
        raw_entries = market.get("entries") or []
        if not isinstance(raw_entries, list):
            raise ValueError(f"{where}.entries: must be a list")
        entries = [parse_entry(e, f"{where}.entries[{i}]") for i, e in enumerate(raw_entries)]
        seen: dict[tuple[date, str], HolidayEntry] = {}
        for entry in entries:
            if entry.key() in seen:
                raise ValueError(f"{where}: duplicate {entry.type} entry on {entry.day}")
            seen[entry.key()] = entry
        if len(
            {e.day for e in entries if e.type == "full_closure"}
            & {e.day for e in entries if e.type != "full_closure"}
        ):
            raise ValueError(f"{where}: a date is both a full closure and a partial session")
        markets[code] = MarketHolidays(
            code=code,
            exchange=_text(market.get("exchange"), f"{where}.exchange"),
            timezone=zone_name,
            source=_text(market.get("source"), f"{where}.source"),
            source_url=_text(market.get("source_url"), f"{where}.source_url"),
            automated=automated,
            entries=tuple(sorted(entries, key=lambda e: (e.day, e.type))),
        )
    return ExchangeCalendar(markets=markets)


def load_exchange_calendar(path: Path) -> ExchangeCalendar:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read exchange calendar {path}: {exc}") from exc
    return parse_exchange_calendar(data)


# --- serialisation ----------------------------------------------------------------------

HEADER = """\
# Exchange holidays: REFERENCE INFORMATION ONLY, not MT5 broker closures.
# Automated markets are updated by `mt5-calendar-update` (weekly GitHub Actions workflow,
# proposed as a pull request for review). Manual markets are maintained by hand.
# The updater never removes or overwrites an existing entry; conflicts are reported instead.
# Broker closures that explain candle gaps belong in market_sessions.yaml `closures`.
"""


def _entry_dict(entry: HolidayEntry) -> dict[str, Any]:
    data: dict[str, Any] = {"date": entry.day.isoformat(), "type": entry.type}
    if entry.at is not None:
        data["time"] = entry.at.strftime("%H:%M")
    data["name"] = entry.name
    data["status"] = entry.status
    data["retrieved"] = entry.retrieved.isoformat()
    if entry.note is not None:
        data["note"] = entry.note
    if entry.source_url is not None:
        data["source_url"] = entry.source_url
    return data


def render_exchange_calendar(calendar: ExchangeCalendar) -> str:
    data = {
        "markets": {
            code: {
                "exchange": m.exchange,
                "timezone": m.timezone,
                "source": m.source,
                "source_url": m.source_url,
                "automated": m.automated,
                "entries": [_entry_dict(e) for e in m.entries],
            }
            for code, m in calendar.markets.items()
        }
    }
    return HEADER + yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)


# --- official source parsers ------------------------------------------------------------


class _TableParser(HTMLParser):
    """Collects the text of every table cell, and the page's plain text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self.text: list[str] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                self.tables.append([])
        elif tag == "tr" and self._depth:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "br":
            self.text.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append(_clean("".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._depth and any(self._row):
                self.tables[-1].append(self._row)
            self._row = None
        elif tag == "table" and self._depth:
            self._depth -= 1
        self.text.append(" ")

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)
        self.text.append(data)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _parse_html(page: str) -> tuple[list[list[list[str]]], str]:
    parser = _TableParser()
    parser.feed(page)
    return parser.tables, _clean("".join(parser.text))


def _checked_date(year: int, month_name: str, day: int, weekday: str, where: str) -> date:
    month = MONTHS.get(month_name.lower())
    if month is None:
        raise SourceError(f"{where}: unknown month {month_name!r}")
    try:
        parsed = date(year, month, day)
    except ValueError as exc:
        raise SourceError(f"{where}: invalid date {day} {month_name} {year}") from exc
    if WEEKDAYS[parsed.weekday()] != weekday.lower():
        raise SourceError(f"{where}: {parsed} is not a {weekday}; source data is inconsistent")
    return parsed


def parse_nyse(page: str, retrieved: date) -> list[HolidayEntry]:
    tables, text = _parse_html(page)
    holiday_tables = [t for t in tables if t and t[0] and t[0][0].lower() == "holiday"]
    if len(holiday_tables) != 1:
        raise SourceError(f"NYSE: expected one holiday table, found {len(holiday_tables)}")
    header, *rows = holiday_tables[0]
    years = []
    for cell in header[1:]:
        if not re.fullmatch(r"\d{4}", cell):
            raise SourceError(f"NYSE: unexpected year header {cell!r}")
        years.append(int(cell))
    if not rows:
        raise SourceError("NYSE: holiday table has no rows")
    entries = []
    for row in rows:
        if len(row) != len(header):
            raise SourceError(f"NYSE: row {row[:1]} has {len(row)} cells, expected {len(header)}")
        name = row[0]
        for year, cell in zip(years, row[1:], strict=True):
            if cell.startswith("—"):  # no holiday that year
                continue
            match = re.match(r"(\w+), (\w+) (\d{1,2})\b", cell)
            if match is None:
                raise SourceError(f"NYSE: cannot read {cell!r} for {name} {year}")
            day = _checked_date(year, match[2], int(match[3]), match[1], f"NYSE {name}")
            entries.append(HolidayEntry(day, "full_closure", name, "confirmed", retrieved))
    early = set()
    for sentence in re.finditer(
        r"Each market will close early at (\d{1,2}):(\d{2}) p\.m\."
        r"(?: \([^)]*\))? on (.*?)(?: \(|\. )",
        text,
    ):
        hour, minute = int(sentence[1]) % 12 + 12, int(sentence[2])
        for found in re.finditer(r"(\w+day), (\w+) (\d{1,2}), (\d{4})", sentence[3]):
            day = _checked_date(int(found[4]), found[2], int(found[3]), found[1], "NYSE early")
            early.add((day, time(hour, minute)))
    entries += [
        HolidayEntry(day, "early_close", "Early close", "confirmed", retrieved, at=at)
        for day, at in sorted(early)
    ]
    return entries


def parse_lse(page: str, retrieved: date) -> list[HolidayEntry]:
    tables, _ = _parse_html(page)
    entries = []
    for table in tables:
        for row in table:
            if not row or not row[0]:
                continue  # header rows have an empty first cell
            match = re.fullmatch(r"(\w+) (\d{1,2}) (\w+) (\d{4})", row[0])
            if match is None or len(row) < 3:
                raise SourceError(f"LSE: unexpected row {row[:2]}")
            day = _checked_date(int(match[4]), match[3], int(match[2]), match[1], "LSE")
            name, status = row[1], row[2]
            early = re.search(r"closing process commences from (\d{1,2}):(\d{2}) London", status)
            if status.startswith("NON-trading day"):
                entries.append(HolidayEntry(day, "full_closure", name, "confirmed", retrieved))
            elif early:
                at = time(int(early[1]), int(early[2]))
                entries.append(
                    HolidayEntry(day, "early_close", name, "confirmed", retrieved, at=at)
                )
            else:
                raise SourceError(f"LSE: cannot interpret status {status!r} on {day}")
    if not entries:
        raise SourceError("LSE: no holiday rows found")
    return entries


def parse_asx(page: str, retrieved: date) -> list[HolidayEntry]:
    tables, text = _parse_html(page)
    early_times = set(
        re.findall(r"Normal trading ceases at (\d{1,2}):(\d{2}) \(Sydney time\)", text)
    )
    entries = []
    for table in tables:
        if not table or len(table[0]) < 3:
            continue
        year_match = re.search(r"Dates for (\d{4})", table[0][1])
        if year_match is None:
            continue
        year = int(year_match[1])
        for row in table[1:]:
            if len(row) < 3:
                raise SourceError(f"ASX: unexpected row {row}")
            name, when, trading = row[0], row[1], row[2].upper()
            match = re.fullmatch(r"(\w+) (\d{1,2}) (\w+)", when)
            if match is None:
                raise SourceError(f"ASX: cannot read date {when!r}")
            day = _checked_date(year, match[3], int(match[2]), match[1], f"ASX {name}")
            if trading.startswith("CLOSED"):
                entries.append(HolidayEntry(day, "full_closure", name, "confirmed", retrieved))
            elif trading.startswith("CLOSE EARLY"):
                if len(early_times) != 1:
                    raise SourceError(f"ASX: early-close time is ambiguous: {sorted(early_times)}")
                ((hour, minute),) = early_times
                at = time(int(hour), int(minute))
                entries.append(
                    HolidayEntry(day, "early_close", name, "confirmed", retrieved, at=at)
                )
            elif trading.startswith("OPEN"):
                continue  # a public holiday on which the market trades normally
            else:
                raise SourceError(f"ASX: cannot interpret trading status {row[2]!r} on {day}")
    if not entries:
        raise SourceError("ASX: no holiday tables found")
    return entries


def parse_nse(payload: str, retrieved: date) -> list[HolidayEntry]:
    try:
        data = json.loads(payload)
        rows = data["CM"]  # capital market segment trading holidays
    except (ValueError, KeyError, TypeError) as exc:
        raise SourceError(f"NSE: unexpected response: {exc}") from exc
    if not isinstance(rows, list) or not rows:
        raise SourceError("NSE: no capital market holidays in response")
    entries = []
    for row in rows:
        try:
            when = datetime.strptime(row["tradingDate"], "%d-%b-%Y").date()
            weekday, name = row["weekDay"], row["description"]
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceError(f"NSE: malformed row {row!r}") from exc
        if WEEKDAYS[when.weekday()] != str(weekday).lower():
            raise SourceError(f"NSE: {when} is not a {weekday}; source data is inconsistent")
        special = [row.get("morning_session"), row.get("evening_session")]
        if any(special):
            # A holiday with a special session (for example Muhurat trading): the closure is
            # not complete, and the session times are not reliably structured.
            entries.append(
                HolidayEntry(
                    when, "full_closure", _text(name, "NSE name"), "unconfirmed", retrieved,
                    note=f"special session listed: {[s for s in special if s]}",
                )
            )  # fmt: skip
        else:
            entries.append(
                HolidayEntry(when, "full_closure", _text(name, "NSE name"), "confirmed", retrieved)
            )
    return entries


@dataclass(frozen=True)
class Source:
    url: str
    parse: Callable[[str, date], list[HolidayEntry]]


SOURCES: Mapping[str, Source] = {
    "US": Source("https://www.nyse.com/markets/hours-calendars", parse_nyse),
    "UK": Source("https://www.londonstockexchange.com/equities-trading/business-days", parse_lse),
    "AU": Source(
        "https://www.asx.com.au/markets/market-resources/trading-hours-calendar/"
        "cash-market-trading-hours/trading-calendar",
        parse_asx,
    ),
    "IN": Source("https://www.nseindia.com/api/holiday-master?type=trading", parse_nse),
}


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    # Verify certificates against the operating system's trust store: some bundled CA files
    # lack newer roots (LSE's chain failed with one). Verification is never disabled.
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    try:
        with urllib.request.urlopen(
            request, timeout=FETCH_TIMEOUT_SECONDS, context=context
        ) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SourceError(f"request to {url} failed: {exc}") from exc
    if len(body) > MAX_RESPONSE_BYTES:
        raise SourceError(f"response from {url} exceeds {MAX_RESPONSE_BYTES} bytes")
    return bytes(body).decode("utf-8", errors="replace")


# --- comparison and report --------------------------------------------------------------


@dataclass
class MarketReport:
    code: str
    source_url: str
    added: list[HolidayEntry] = field(default_factory=list)
    conflicts: list[tuple[HolidayEntry, HolidayEntry]] = field(default_factory=list)
    missing_from_source: list[HolidayEntry] = field(default_factory=list)
    error: str | None = None


def merge_market(
    market: MarketHolidays, fetched: Sequence[HolidayEntry]
) -> tuple[MarketHolidays, MarketReport]:
    """Add new entries only. Conflicts and source omissions are reported, never applied, and
    any conflict leaves the market unchanged."""
    report = MarketReport(market.code, market.source_url)
    by_key: dict[tuple[date, str], HolidayEntry] = {}
    for entry in fetched:
        if entry.key() in by_key and not by_key[entry.key()].same_content(entry):
            report.error = f"source lists conflicting {entry.type} entries on {entry.day}"
            return market, report
        by_key[entry.key()] = entry
    local = {e.key(): e for e in market.entries}
    local_dates = {e.day: e for e in market.entries}
    for key, entry in sorted(by_key.items()):
        existing = local.get(key)
        if existing is None and entry.day in local_dates:
            report.conflicts.append((local_dates[entry.day], entry))  # same day, other type
        elif existing is None:
            report.added.append(entry)
        elif not existing.same_content(entry):
            report.conflicts.append((existing, entry))
    if by_key:
        first, last = min(k[0] for k in by_key), max(k[0] for k in by_key)
        report.missing_from_source = [
            e for e in market.entries if first <= e.day <= last and e.key() not in by_key
        ]
    if report.conflicts:
        report.added = []
        return market, report
    merged = tuple(sorted([*market.entries, *report.added], key=lambda e: (e.day, e.type)))
    return replace(market, entries=merged), report


def update_calendar(
    calendar: ExchangeCalendar,
    *,
    today: date,
    fetcher: Callable[[str], str] = fetch,
    sources: Mapping[str, Source] = SOURCES,
) -> tuple[ExchangeCalendar, list[MarketReport]]:
    markets = dict(calendar.markets)
    reports = []
    for code, market in calendar.markets.items():
        source = sources.get(code)
        if not market.automated or source is None:
            continue
        try:
            fetched = source.parse(fetcher(source.url), today)
        except SourceError as exc:
            reports.append(MarketReport(code, source.url, error=str(exc)))
            continue
        markets[code], report = merge_market(market, fetched)
        reports.append(report)
    return ExchangeCalendar(markets=markets), reports


def _describe(entry: HolidayEntry) -> str:
    at = f" {entry.at:%H:%M}" if entry.at else ""
    return f"{entry.day} {entry.type}{at} {entry.name} ({entry.status})"


def render_report(reports: Sequence[MarketReport], calendar: ExchangeCalendar) -> str:
    lines = ["## Exchange holiday calendar update", ""]
    lines.append(
        "Reference information only. These entries do not change MT5 broker sessions; "
        "confirmed broker closures belong in `config/market_sessions.yaml`."
    )
    for report in reports:
        lines += ["", f"### {report.code}: <{report.source_url}>"]
        if report.error:
            lines.append(f"- **Source failed, local entries kept:** {report.error}")
            continue
        lines += [f"- Added: {_describe(e)}" for e in report.added] or ["- No additions"]
        lines += [
            f"- **Conflict, not applied:** local {_describe(old)}; source {_describe(new)}"
            for old, new in report.conflicts
        ]
        lines += [
            f"- **No longer listed by source, kept:** {_describe(e)}"
            for e in report.missing_from_source
        ]
    manual = [m for m in calendar.markets.values() if not m.automated]
    if manual:
        lines += ["", "### Not automated (maintain by hand)"]
        lines += [f"- {m.code} {m.exchange}: <{m.source_url}>" for m in manual]
    return "\n".join(lines) + "\n"


def needs_attention(reports: Sequence[MarketReport]) -> bool:
    return any(r.error or r.conflicts or r.missing_from_source for r in reports)


def main(
    argv: Sequence[str] | None = None,
    *,
    fetcher: Callable[[str], str] = fetch,
    today: date | None = None,
) -> int:
    parser = argparse.ArgumentParser(description="Update the exchange holiday reference file.")
    parser.add_argument("--calendar", type=Path, default=Path("config/exchange_holidays.yaml"))
    parser.add_argument("--report", type=Path, help="Write a Markdown report here")
    args = parser.parse_args(argv)

    try:
        current = load_exchange_calendar(args.calendar)
    except ValueError as exc:
        print(f"Local calendar is invalid; nothing changed: {exc}", file=sys.stderr)
        return 2
    updated, reports = update_calendar(current, today=today or date.today(), fetcher=fetcher)
    report = render_report(reports, updated)
    if args.report:
        args.report.write_text(report, encoding="utf-8")
    print(report)
    if updated != current:
        # Validate what will be written by reading it back before replacing the file.
        text = render_exchange_calendar(updated)
        parse_exchange_calendar(yaml.safe_load(text))
        temporary = args.calendar.with_suffix(".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(args.calendar)
    return 1 if needs_attention(reports) else 0


if __name__ == "__main__":
    raise SystemExit(main())
