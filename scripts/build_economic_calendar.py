"""Build config/economic_calendar.yaml from official pages saved under data/calendar/raw/.

Sources (official only):
- FOMC meetings: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
- Each FOMC statement's release time: its own press release page
  (https://www.federalreserve.gov/newsevents/pressreleases/monetaryYYYYMMDDa.htm), "For
  release at h:mm a.m./p.m. EDT|EST". The date and the EDT/EST label are checked against the
  link date and US daylight saving; any disagreement stops the build.
- BLS CPI and Employment Situation: bls.gov refuses automated access (HTTP 403), so the owner
  saves the official schedule and archive pages in a browser (scripts/save_bls_pages.sh, which
  records each file's URL, sha256 and save time in data/calendar/raw/bls/MANIFEST.tsv).
  Publication dates come from the archive, release times from the schedule
  (src/trading/research/bls_calendar.py). Without those files both stay "unavailable".

Nothing is invented: a meeting without a published statement page (a future meeting) is kept
as "scheduled" with no time; the news filter then blocks its whole New York day.

    uv run python scripts/build_economic_calendar.py
"""

import hashlib
import re
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from trading.research.bls_calendar import (
    ARCHIVE_NAMES,
    apply_release_times,
    build_events,
    not_published,
    parse_archive,
    parse_schedule,
)

RAW = Path("data/calendar/raw")
BLS = RAW / "bls"
BLS_PAGES = {  # kind -> (schedule file, archive file)
    "cpi": ("cpi_schedule.html", "cpi_archive.html"),
    "employment_situation": ("empsit_schedule.html", "empsit_archive.html"),
}
OUT = Path("config/economic_calendar.yaml")
FED = "https://www.federalreserve.gov"
CALENDAR_URL = f"{FED}/monetarypolicy/fomccalendars.htm"
COVERAGE_FROM = date(2022, 11, 1)  # earliest statement page verified (the backtest warm-up)
NY = ZoneInfo("America/New_York")
MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September",
     "October", "November", "December"], start=1)}  # fmt: skip


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def retrieved(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat(timespec="seconds")


def _text(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>|&nbsp;", " ", raw))


def meetings(calendar_html: str) -> list[dict[str, object]]:
    """Every meeting row: year, month label, date label, statement link date (if published)."""
    out = []
    parts = re.split(r"(\d{4}) FOMC Meetings</a>", calendar_html)
    for k in range(1, len(parts), 2):
        year, body = int(parts[k]), parts[k + 1]
        rows = re.findall(r'<div class="[^"]*fomc-meeting"[^>]*>(.*?)(?=<div class="[^"]*row '
                          r'fomc-meeting"|\Z)', body, flags=re.S)  # fmt: skip
        for row in rows:
            month = re.search(r"fomc-meeting__month[^>]*><strong>(.*?)</strong>", row)
            day = re.search(r"fomc-meeting__date[^>]*>(.*?)</div>", row)
            link = re.search(r"pressreleases/monetary(\d{8})a\.htm", row)
            if not month or not day:
                raise SystemExit(f"unparsed meeting row in {year}")
            out.append({"year": year, "month": month.group(1), "days": day.group(1).strip(),
                        "statement": link.group(1) if link else None})  # fmt: skip
    return out


def last_day(year: int, month_label: str, days: str) -> date:
    """Final day of a meeting from labels like 'March', '17-18*', 'Jan/Feb', '31-1'."""
    months = month_label.split("/")
    month = MONTHS.get(months[-1]) or next(
        i for name, i in MONTHS.items() if name.startswith(months[-1])
    )
    final = int(re.findall(r"\d+", days)[-1])
    return date(year, month, final)


def main() -> None:
    page = RAW / "fomccalendars.html"
    rows = meetings(page.read_text(encoding="utf-8"))
    events, sources = [], [{"url": CALENDAR_URL, "file": str(page), "sha256": sha(page),
                            "retrieved_utc": retrieved(page)}]  # fmt: skip
    latest_verified = COVERAGE_FROM
    for row in rows:
        if row["statement"] is None:
            day = last_day(int(row["year"]), str(row["month"]), str(row["days"]))  # type: ignore[call-overload]
            if day >= date.today():
                events.append({"kind": "fomc_statement", "date": day.isoformat(), "time": None,
                               "status": "scheduled", "source": CALENDAR_URL,
                               "note": "future meeting; release time not yet published"},
                              )  # fmt: skip
            continue
        link_day = datetime.strptime(str(row["statement"]), "%Y%m%d").date()
        if link_day < COVERAGE_FROM:
            continue
        path = RAW / "fomc" / f"monetary{row['statement']}a.htm"
        if not path.exists():
            raise SystemExit(f"statement page not saved: {path}")
        text = _text(path)
        m = re.search(r"([A-Z][a-z]+ \d{1,2}, \d{4}) .{0,400}?For release at\s*(\d{1,2}):(\d{2})"
                      r"\s*([ap])\.m\.\s*(EDT|EST)", text)  # fmt: skip
        if not m:
            raise SystemExit(f"no release date/time on {path}")
        stated = datetime.strptime(m.group(1), "%B %d, %Y").date()
        if stated != link_day:
            raise SystemExit(f"{path}: page date {stated} differs from link date {link_day}")
        hour = int(m.group(2)) % 12 + (12 if m.group(4) == "p" else 0)
        clock = f"{hour:02d}:{m.group(3)}"
        moment = datetime.combine(stated, datetime.strptime(clock, "%H:%M").time(), tzinfo=NY)
        if moment.tzname() != m.group(5):
            raise SystemExit(
                f"{path}: {m.group(5)} disagrees with US daylight saving ({moment.tzname()})"
            )
        url = f"{FED}/newsevents/pressreleases/monetary{row['statement']}a.htm"
        note = "notation vote" if "notation" in str(row["days"]) else "scheduled meeting"
        events.append({"kind": "fomc_statement", "date": stated.isoformat(), "time": clock,
                       "status": "published", "source": url, "note": note})  # fmt: skip
        sources.append({"url": url, "file": str(path), "sha256": sha(path),
                        "retrieved_utc": retrieved(path)})  # fmt: skip
        latest_verified = max(latest_verified, stated)
    calendar_retrieved = datetime.fromtimestamp(page.stat().st_mtime, tz=UTC).date()
    data = {
        "description": "Official economic calendar for research backtests (news restriction).",
        "timezone": "America/New_York",
        "built_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "coverage": [
            {
                "kind": "fomc_statement",
                "from": COVERAGE_FROM.isoformat(),
                "to": calendar_retrieved.isoformat(),
                "note": "every meeting and notation-vote statement listed on the Fed calendar page "
                "in this range, each time verified on its release page",
            },
            {
                "kind": "fomc_statement",
                "from": calendar_retrieved.isoformat(),
                "to": f"{max(int(r['year']) for r in rows)}-12-31",  # type: ignore[call-overload]
                "note": "scheduled meetings only (dates from the Fed calendar page; release times "
                "not yet published, so each meeting blocks its whole New York day)",
            },
        ],  # fmt: skip
        "unavailable": {},
        "findings": [],
        "events": [],
        "sources": sources,
    }
    for kind, (schedule_file, archive_file) in BLS_PAGES.items():
        added = add_bls(kind, BLS / schedule_file, BLS / archive_file, data)
        if not added:
            data["unavailable"][kind] = (  # type: ignore[index]
                "bls.gov refuses automated access (HTTP 403); official pages not saved in "
                f"{BLS} (run scripts/save_bls_pages.sh)"
            )
    data["events"] = sorted([*events, *data["events"]],  # type: ignore[misc]
                            key=lambda e: (str(e["date"]), str(e["time"])))  # fmt: skip
    for finding in data["findings"]:  # type: ignore[attr-defined]
        print(f"finding: {finding}")
    OUT.write_text(yaml.safe_dump(data, sort_keys=False, width=100), encoding="utf-8")
    published = sum(e["status"] == "published" for e in events)
    print(
        f"{OUT}: {published} published FOMC statements ({COVERAGE_FROM} to "
        f"{latest_verified}), {len(events) - published} scheduled"
    )


def bls_manifest() -> dict[str, dict[str, str]]:
    """Rows of data/calendar/raw/bls/MANIFEST.tsv (written by scripts/save_bls_pages.sh)."""
    path = BLS / "MANIFEST.tsv"
    if not path.exists():
        return {}
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    return {row[0]: dict(zip(header, row, strict=True))
            for row in (line.split("\t") for line in lines[1:] if line)}  # fmt: skip


def saved_releases(kind: str) -> tuple[dict[date, str], list[dict[str, str]]]:
    """Release documents downloaded by scripts/download_bls_releases.sh, each checked against
    the sha256 recorded at download (data/calendar/raw/bls/releases/MANIFEST.tsv)."""
    folder = BLS / "releases"
    manifest = folder / "MANIFEST.tsv"
    if not manifest.exists():
        return {}, []
    lines = manifest.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    out, sources = {}, []
    for row in (dict(zip(header, line.split("\t"), strict=True)) for line in lines[1:] if line):
        name = row["file"]
        if not name.startswith(f"{ARCHIVE_NAMES[kind]}_"):
            continue
        path = folder / name
        if not path.exists() or sha(path) != row["sha256"]:
            raise SystemExit(f"{path} is missing or changed since download; download it again")
        day = datetime.strptime(name.split("_")[1][:8], "%m%d%Y").date()
        out[day] = path.read_text(encoding="utf-8", errors="ignore")
        sources.append({"url": row["url"], "file": str(path), "sha256": row["sha256"],
                        "retrieved_utc": row["downloaded_utc"]})  # fmt: skip
    return out, sources


def add_bls(kind: str, schedule_path: Path, archive_path: Path, data: dict[str, object]) -> bool:
    """Add one BLS release to ``data`` from the saved pages; False when they are not saved.
    Each file must match the sha256 recorded when it was saved, so the calendar is built from
    exactly the verified pages."""
    manifest = bls_manifest()
    files = (schedule_path, archive_path)
    if not all(p.exists() and p.name in manifest for p in files):
        return False
    for p in files:
        if sha(p) != manifest[p.name]["sha256"]:
            raise SystemExit(f"{p} changed since it was saved and verified; save it again")
    schedule = parse_schedule(schedule_path.read_text(encoding="utf-8", errors="ignore"))
    archive_html = archive_path.read_text(encoding="utf-8", errors="ignore")
    archive = parse_archive(archive_html, kind)
    if not schedule or not archive:
        raise SystemExit(f"{kind}: no {'schedule rows' if not schedule else 'archive links'} "
                         "found; the saved page layout is not the one expected")  # fmt: skip
    saved = min(datetime.fromisoformat(manifest[p.name]["saved_utc"].replace("Z", "+00:00"))
                for p in files).date()  # fmt: skip
    urls = (manifest[schedule_path.name]["url"], manifest[archive_path.name]["url"])
    built = build_events(kind, schedule, archive, saved, COVERAGE_FROM, *urls)
    built.findings.extend(
        f"{kind}: BLS archive says: {note}" for note in not_published(archive_html)
    )
    releases, release_sources = saved_releases(kind)
    built.findings.extend(apply_release_times(kind, built.events, releases))
    data["sources"].extend(release_sources)  # type: ignore[attr-defined]
    untimed = sum(e["time"] is None for e in built.events)
    if untimed:
        built.findings.append(
            f"{kind}: {untimed} publications without a release time on the saved schedule "
            "page (each blocks its whole New York day)")  # fmt: skip
    data["events"].extend(built.events)  # type: ignore[attr-defined]
    data["coverage"].extend(built.coverage)  # type: ignore[attr-defined]
    data["findings"].extend(built.findings)  # type: ignore[attr-defined]
    for p in files:
        row = manifest[p.name]
        data["sources"].append({"url": row["url"], "file": str(p), "sha256": row["sha256"],  # type: ignore[attr-defined]
                                "retrieved_utc": row["saved_utc"],
                                "saved_by": "owner, in a browser"})  # fmt: skip
    print(
        f"{kind}: {sum(e['status'] == 'published' for e in built.events)} published, "
        f"{sum(e['status'] == 'scheduled' for e in built.events)} scheduled"
    )
    return True


if __name__ == "__main__":
    main()
