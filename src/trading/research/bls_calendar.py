"""BLS CPI and Employment Situation release dates from official pages saved by the owner in a
browser (bls.gov refuses automated access; see scripts/save_bls_pages.sh).

Two kinds of official page are used for each release:
- the **release schedule** (bls.gov/schedule/news_release/<release>.htm): reference month,
  release date and release time (Eastern Time);
- the **news release archive** (bls.gov/bls/news-release/<release>.htm): links to every
  published release, named <release>_MMDDYYYY, i.e. the actual publication dates.

Nothing is invented. An archived publication date takes its time from the schedule row for
that date; without one, its time is left empty and the news filter blocks the whole New York
day. Disagreements (a scheduled date with no archived publication, gaps between releases) are
returned as findings for the calendar file and the report.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8,
          "sep": 9, "oct": 10, "nov": 11, "dec": 12}  # fmt: skip
ARCHIVE_NAMES = {"cpi": "cpi", "employment_situation": "empsit"}
_DATE = re.compile(r"\b([A-Z][a-z]{2,8})\.?\s+(\d{1,2}),\s+(\d{4})\b")
_TIME = re.compile(r"\b(\d{1,2}):(\d{2})\s*([AaPp])\.?\s*[Mm]\.?")
MAX_GAP = timedelta(days=45)  # both releases are monthly


@dataclass(frozen=True)
class ScheduledRelease:
    day: date
    release_time: time
    row_text: str  # the schedule row as published, for verification


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>|&nbsp;", " ", html)).strip()


def _month(name: str) -> int | None:
    return MONTHS.get(name[:3].lower())


def parse_schedule(html: str) -> list[ScheduledRelease]:
    """Rows of a BLS release-schedule table that state a full release date and a time."""
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S | re.I):
        text = _text(row)
        found_date, found_time = _DATE.search(text), _TIME.search(text)
        if not found_date or not found_time:
            continue
        month = _month(found_date.group(1))
        if month is None:
            continue
        hour = int(found_time.group(1)) % 12 + (12 if found_time.group(3).lower() == "p" else 0)
        out.append(ScheduledRelease(
            date(int(found_date.group(3)), month, int(found_date.group(2))),
            time(hour, int(found_time.group(2))), text))  # fmt: skip
    return sorted(set(out), key=lambda r: r.day)


def _uncommented(html: str) -> str:
    """The page without HTML comments: BLS keeps unpublished placeholder links in them."""
    return re.sub(r"<!--.*?-->", "", html, flags=re.S)


def not_published(html: str) -> list[str]:
    """Archive entries BLS marks as not published (e.g. the 2025 appropriations lapse)."""
    items = re.findall(r"<li[^>]*>(.*?)</li>", _uncommented(html), flags=re.S | re.I)
    return [_text(i).replace("&ndash;", "-") for i in items if "not published" in i.lower()]


def parse_archive(html: str, kind: str) -> list[date]:
    """Publication dates from the archive links (<name>_MMDDYYYY.htm or .pdf), ignoring links
    inside HTML comments (unpublished placeholders)."""
    name = ARCHIVE_NAMES[kind]
    days = set()
    for stamp in re.findall(rf"archives/{name}_(\d{{8}})\.(?:htm|pdf)", _uncommented(html),
                            flags=re.I):  # fmt: skip
        days.add(datetime.strptime(stamp, "%m%d%Y").date())
    return sorted(days)


@dataclass(frozen=True)
class BlsCalendar:
    events: list[dict[str, object]]
    coverage: list[dict[str, str]]
    findings: list[str]


def build_events(
    kind: str,
    schedule: Iterable[ScheduledRelease],
    archive: Iterable[date],
    retrieved: date,
    coverage_from: date,
    schedule_url: str,
    archive_url: str,
) -> BlsCalendar:
    by_day = {r.day: r for r in schedule}
    published = sorted(d for d in set(archive) if d >= coverage_from and d <= retrieved)
    events: list[dict[str, object]] = []
    findings: list[str] = []
    for day in published:
        row = by_day.get(day)
        events.append({
            "kind": kind, "date": day.isoformat(),
            "time": row.release_time.strftime("%H:%M") if row else None,
            "status": "published", "source": archive_url,
            "note": ("publication date from the archive; time from the schedule row "
                     f"'{row.row_text}'" if row else "publication date from the archive; "
                     "release time not on the saved schedule page (whole day blocked)"),
        })  # fmt: skip
    for day, row in sorted(by_day.items()):
        if day < coverage_from or day in published:
            continue
        status = "scheduled"
        if day <= retrieved:
            findings.append(f"{kind}: scheduled {day} ({row.row_text}) has no archived "
                            "publication on that date (delayed, cancelled or not yet archived); "
                            "kept as a scheduled event")  # fmt: skip
        events.append({"kind": kind, "date": day.isoformat(),
                       "time": row.release_time.strftime("%H:%M"), "status": status,
                       "source": schedule_url,
                       "note": f"schedule row '{row.row_text}'"})  # fmt: skip
    for earlier, later in zip(published, published[1:], strict=False):
        if later - earlier > MAX_GAP:
            findings.append(f"{kind}: {(later - earlier).days} days between publications "
                            f"{earlier} and {later}")  # fmt: skip
    coverage: list[dict[str, str]] = []
    if published:
        start = coverage_from
        if published[0] - coverage_from > MAX_GAP:
            start = published[0]
            findings.append(f"{kind}: archive starts {published[0]}, after {coverage_from}; "
                            "coverage starts there")  # fmt: skip
        coverage.append({"kind": kind, "from": start.isoformat(), "to": retrieved.isoformat(),
                         "note": "publication dates from the BLS archive page saved on "
                                 f"{retrieved}"})  # fmt: skip
    future = [d for d in by_day if d > retrieved]
    if future:
        coverage.append({"kind": kind, "from": retrieved.isoformat(),
                         "to": max(future).isoformat(),
                         "note": "scheduled releases from the BLS schedule page"})  # fmt: skip
    events.sort(key=lambda e: str(e["date"]))
    return BlsCalendar(events, coverage, findings)


_EMBARGO = re.compile(
    r"embargoed\s+until\s+(?:USDL-[\d-]+\s+)?(\d{1,2}):(\d{2})\s*([ap])\.?\s*m\.?\s*\(?\s*(?:ET|EDT|EST|Eastern)?"
    r"[^A-Za-z0-9]*(?:[A-Z][a-z]+day,?\s+)?([A-Z][a-z]+)\.?\s+(\d{1,2}),\s+(\d{4})",
    flags=re.I,
)


def embargo(html: str) -> tuple[date, time] | None:
    """Release date and time from a release's embargo statement, e.g. "Transmission of material
    in this release is embargoed until 8:30 a.m. (ET) Wednesday, November 13, 2024"."""
    m = _EMBARGO.search(_text(html))
    if not m:
        return None
    month = _month(m.group(4))
    if month is None:
        return None
    hour = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "p" else 0)
    return date(int(m.group(6)), month, int(m.group(5))), time(hour, int(m.group(2)))


def apply_release_times(
    kind: str, events: list[dict[str, object]], releases: dict[date, str]
) -> list[str]:
    """Fill missing times of published events from their own release documents (date -> HTML).
    A release whose embargo date differs from the archive date is reported, not used."""
    findings = []
    for event in events:
        if event["status"] != "published":
            continue
        day = date.fromisoformat(str(event["date"]))
        html = releases.get(day)
        if html is None:
            continue
        found = embargo(html)
        if found is None:
            findings.append(f"{kind}: {day} release has no readable embargo statement")
            continue
        stated, clock = found
        if stated != day:
            findings.append(f"{kind}: {day} release says {stated}; time not used")
            continue
        if event["time"] is not None and event["time"] != clock.strftime("%H:%M"):
            findings.append(f"{kind}: {day} schedule time {event['time']} differs from the "
                            f"release's {clock:%H:%M}; release time used")  # fmt: skip
        event["time"] = clock.strftime("%H:%M")
        event["note"] = (f"publication date from the archive; time from the release's embargo "
                         f"statement ({clock:%H:%M} ET, {stated})")  # fmt: skip
    return findings
