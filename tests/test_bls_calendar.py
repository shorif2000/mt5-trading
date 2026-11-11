"""BLS calendar from saved official pages: parsing, missing dates, daylight saving, coverage.

The HTML below is synthetic, shaped like the BLS release-schedule table and news-release
archive list. The real saved pages are checked by the builder, which stops if it finds no
schedule rows or archive links.
"""

from datetime import UTC, date, datetime, time

import pytest

from trading.research.bls_calendar import (
    apply_release_times,
    build_events,
    embargo,
    embargo_statement,
    not_published,
    parse_archive,
    parse_schedule,
)
from trading.research.news import Calendar, Coverage, EconomicEvent, NewsFilter

SCHEDULE = """
<table><tr><th>Reference Month</th><th>Release Date</th><th>Release Time</th></tr>
<tr><td>Feb. 2024</td><td>Mar. 12, 2024</td><td>08:30 AM</td></tr>
<tr><td>Aug. 2024</td><td>Sept. 11, 2024</td><td>08:30 AM</td></tr>
<tr><td>Oct. 2024</td><td>Nov. 13, 2024</td><td>08:30 AM</td></tr>
<tr><td>Nov. 2026</td><td>Dec. 10, 2026</td><td>08:30 AM</td></tr>
</table>"""
ARCHIVE = """
<ul><li>CPI for February 2024 <a href="/news.release/archives/cpi_03122024.htm">HTML</a>
<a href="/news.release/archives/cpi_03122024.pdf">PDF</a></li>
<li>CPI for March 2024 <a href="/news.release/archives/cpi_04102024.htm">HTML</a></li>
<li>CPI for August 2024 <a href="/news.release/archives/cpi_09112024.htm">HTML</a></li>
<li>Employment <a href="/news.release/archives/empsit_03082024.htm">HTML</a></li>
<li>October 2025 Consumer Price Index &ndash; Not published because of 2025 lapse in federal
government appropriations</li>
<!-- <li><a href="/news.release/archives/cpi_12102026.htm">November 2026 CPI</a></li> --></ul>"""
URLS = ("https://www.bls.gov/schedule/news_release/cpi.htm",
        "https://www.bls.gov/bls/news-release/cpi.htm")  # fmt: skip


def built(retrieved=date(2026, 11, 11), coverage_from=date(2024, 3, 1)):
    return build_events("cpi", parse_schedule(SCHEDULE), parse_archive(ARCHIVE, "cpi"),
                        retrieved, coverage_from, *URLS)  # fmt: skip


def test_schedule_rows_give_dates_and_eastern_times_including_sept():
    rows = parse_schedule(SCHEDULE)
    assert [r.day for r in rows] == [date(2024, 3, 12), date(2024, 9, 11), date(2024, 11, 13),
                                     date(2026, 12, 10)]  # fmt: skip
    assert {r.release_time for r in rows} == {time(8, 30)}


def test_archive_links_give_publication_dates_for_that_release_only():
    assert parse_archive(ARCHIVE, "cpi") == [date(2024, 3, 12), date(2024, 4, 10),
                                             date(2024, 9, 11)]  # fmt: skip
    assert parse_archive(ARCHIVE, "employment_situation") == [date(2024, 3, 8)]


def test_publication_without_a_schedule_time_is_kept_without_inventing_one():
    events = {e["date"]: e for e in built().events}
    assert events["2024-03-12"]["time"] == "08:30" and events["2024-03-12"]["status"] == "published"
    assert events["2024-04-10"]["time"] is None  # archived, but not on the saved schedule


def test_missing_and_unconfirmed_dates_are_reported_not_filled():
    result = built()
    # 2024-04-10 to 2024-09-11 is far longer than one month: releases missing from the archive.
    assert any("154 days between publications 2024-04-10 and 2024-09-11" in f
               for f in result.findings)  # fmt: skip
    # Scheduled 2024-11-13 but not archived: kept (it blocks), and flagged.
    assert any("2024-11-13" in f and "no archived publication" in f for f in result.findings)
    assert "2024-05-15" not in {e["date"] for e in result.events}  # nothing invented


def test_coverage_runs_from_the_start_to_the_save_date_then_scheduled_only():
    result = built()
    assert result.coverage[0] == {"kind": "cpi", "from": "2024-03-01", "to": "2026-11-11",
                                  "note": "publication dates from the BLS archive page saved on "
                                          "2026-11-11"}  # fmt: skip
    assert result.coverage[1]["from"] == "2026-11-11" and result.coverage[1]["to"] == "2026-12-10"


def test_coverage_starts_at_the_archive_when_it_begins_later_than_required():
    result = built(coverage_from=date(2023, 1, 1))
    assert result.coverage[0]["from"] == "2024-03-12"
    assert any("archive starts 2024-03-12" in f for f in result.findings)


@pytest.mark.parametrize(
    ("day", "blocked_utc", "allowed_utc"),
    [(date(2024, 3, 8), datetime(2024, 3, 8, 13, 0, tzinfo=UTC),  # EST: 08:30 = 13:30 UTC
      datetime(2024, 3, 8, 12, 30, tzinfo=UTC)),
     (date(2024, 3, 12), datetime(2024, 3, 12, 12, 0, tzinfo=UTC),  # EDT: 08:30 = 12:30 UTC
      datetime(2024, 3, 12, 13, 0, tzinfo=UTC))],
    ids=["before-DST-change", "after-DST-change"],
)  # fmt: skip
def test_0830_eastern_moves_in_utc_across_the_daylight_saving_change(day, blocked_utc,
                                                                      allowed_utc):  # fmt: skip
    cal = Calendar((EconomicEvent("cpi", day, time(8, 30), "published", "test"),),
                   (Coverage("cpi", date(2024, 1, 1), date(2024, 12, 31)),), {})  # fmt: skip
    f = NewsFilter(cal, ["cpi"])
    assert f.check(blocked_utc) is not None  # 08:00 Eastern, inside 08:00-08:45
    assert f.check(allowed_utc) is None


def test_dates_before_bls_coverage_fail_closed():
    cal = Calendar((), tuple(Coverage(c["kind"], date.fromisoformat(c["from"]),
                                      date.fromisoformat(c["to"])) for c in built().coverage),
                   {})  # fmt: skip
    f = NewsFilter(cal, ["cpi"])
    assert f.check(datetime(2024, 2, 1, 15, 0, tzinfo=UTC)) == "economic calendar unavailable (cpi)"


def test_placeholder_links_inside_html_comments_are_not_publications():
    assert date(2026, 12, 10) not in parse_archive(ARCHIVE, "cpi")


def test_releases_bls_marks_as_not_published_are_reported():
    [note] = not_published(ARCHIVE)
    assert note.startswith("October 2025 Consumer Price Index - Not published because of 2025")


RELEASE = """<pre>Transmission of material in this release is embargoed until
8:30 a.m. (ET) Wednesday, April 10, 2024</pre>"""


def test_release_embargo_statement_gives_the_verified_time():
    assert embargo(RELEASE) == (date(2024, 4, 10), time(8, 30))
    events = built().events
    findings = apply_release_times("cpi", events, {date(2024, 4, 10): RELEASE})
    event = next(e for e in events if e["date"] == "2024-04-10")
    assert event["time"] == "08:30" and "embargo statement" in str(event["note"])
    assert findings == []


def test_a_release_dated_differently_from_the_archive_is_reported_not_used():
    events = built().events
    findings = apply_release_times("cpi", events, {date(2024, 3, 12): RELEASE})
    assert findings == ["cpi: 2024-03-12 release says 2024-04-10; time not used"]
    assert next(e for e in events if e["date"] == "2024-04-10")["time"] is None


def test_embargo_statement_with_the_release_number_before_the_time():
    # Employment Situation wording, as published (2024-03-08 release).
    html = (
        "<p>Transmission of material in this news release is embargoed until</p> "
        "<p>USDL-24-0451</p> <p>8:30 a.m. (ET) Friday, March 8, 2024</p>"
    )
    assert embargo(html) == (date(2024, 3, 8), time(8, 30))


def test_stored_embargo_statement_parses_back_to_the_same_date_and_time():
    # data/calendar/bls_release_evidence.tsv keeps only this sentence for each release.
    statement = embargo_statement(RELEASE)
    assert statement == "embargoed until 8:30 a.m. (ET) Wednesday, April 10, 2024"
    assert embargo(statement) == embargo(RELEASE)
