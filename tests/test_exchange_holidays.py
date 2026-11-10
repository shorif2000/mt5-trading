"""Official-source parsing and the safe update of the exchange holiday reference file."""

import json
from datetime import date, time
from pathlib import Path

import pytest

from trading.market_data.exchange_holidays import (
    SOURCES,
    ExchangeCalendar,
    HolidayEntry,
    MarketHolidays,
    SourceError,
    load_exchange_calendar,
    main,
    merge_market,
    parse_asx,
    parse_exchange_calendar,
    parse_lse,
    parse_nse,
    parse_nyse,
    render_exchange_calendar,
    update_calendar,
)

TODAY = date(2026, 11, 10)

NYSE_PAGE = """
<table><tr><th>Holiday</th><th>2026</th><th>2027</th></tr>
<tr><td>New Year&rsquo;s Day</td><td>Thursday, January 1</td><td>Friday, January 1</td></tr>
<tr><td>Independence Day</td><td>Friday, July 3 (Independence Day observed)</td>
    <td>Monday, July 5 (Independence Day observed)</td></tr>
<tr><td>Thanksgiving Day</td><td>Thursday, November 26***</td><td>—*</td></tr>
</table>
<p>*** Each market will close early at 1:00 p.m. (1:15 p.m. for eligible options) on
Friday, November 27, 2026 (the day after Thanksgiving). All times are Eastern Time.</p>
"""

LSE_PAGE = """
<table><tr><td></td><td></td><td>On Exchange Trading Services</td></tr>
<tr><td>Thursday 24 December 2026</td><td>Christmas Holiday half day</td>
    <td>Markets closing process commences from 12:30 London time. Standard settlement day.</td></tr>
<tr><td>Friday 25 December 2026</td><td>Christmas Day</td>
    <td>NON-trading day. Also GBX/ GBP NON-settlement day in EUI</td></tr>
</table>
"""

ASX_PAGE = """
<table><tr><th>Public holiday</th><th>Dates for 2026</th><th>Trading day [1]</th></tr>
<tr><td>Good Friday</td><td>Friday 3 April</td><td>CLOSED</td></tr>
<tr><td>ANZAC Day</td><td>Saturday 25 April</td><td>OPEN [2]</td></tr>
<tr><td>Last Business day of the Year</td><td>Thursday 31 December</td><td>CLOSE EARLY [3]</td></tr>
</table>
<p>[3] Normal trading ceases at 14:10 (Sydney time).</p>
"""


def nse_payload(rows: list[dict[str, object]]) -> str:
    return json.dumps({"CM": rows})


def nse_row(day: str, weekday: str, name: str, session: str | None = None) -> dict[str, object]:
    return {"tradingDate": day, "weekDay": weekday, "description": name,
            "morning_session": None, "evening_session": session}  # fmt: skip


def entry(day: date, name: str, kind: str = "full_closure", at: time | None = None,
          status: str = "confirmed") -> HolidayEntry:  # fmt: skip
    return HolidayEntry(day, kind, name, status, TODAY, at=at)  # type: ignore[arg-type]


def market(entries: tuple[HolidayEntry, ...] = (), code: str = "US") -> MarketHolidays:
    return MarketHolidays(
        code, "NYSE", "America/New_York", "NYSE", SOURCES["US"].url, True, entries
    )


# --- official source parsing ------------------------------------------------------------


def test_nyse_full_closures_use_observed_dates_and_footnoted_early_closes():
    entries = parse_nyse(NYSE_PAGE, TODAY)
    full = {(e.day, e.name) for e in entries if e.type == "full_closure"}
    assert (date(2026, 7, 3), "Independence Day") in full  # observed Friday, not 4 July
    assert (date(2027, 7, 5), "Independence Day") in full
    assert not any(e.day.year == 2027 and e.name == "Thanksgiving Day" for e in entries)  # "—"
    early = [e for e in entries if e.type == "early_close"]
    assert [(e.day, e.at) for e in early] == [(date(2026, 11, 27), time(13, 0))]
    assert all(e.status == "confirmed" and e.retrieved == TODAY for e in entries)


def test_nyse_date_with_wrong_weekday_is_rejected():
    page = NYSE_PAGE.replace("Thursday, January 1", "Monday, January 1")
    with pytest.raises(SourceError, match="not a Monday"):
        parse_nyse(page, TODAY)


def test_nyse_unreadable_cell_is_rejected():
    with pytest.raises(SourceError, match="cannot read"):
        parse_nyse(NYSE_PAGE.replace("Thursday, January 1", "To be announced"), TODAY)


def test_nyse_page_without_holiday_table_is_rejected():
    with pytest.raises(SourceError, match="expected one holiday table"):
        parse_nyse("<html><body>Maintenance</body></html>", TODAY)


def test_lse_half_day_is_an_early_close_in_london_time():
    entries = parse_lse(LSE_PAGE, TODAY)
    assert [(e.day, e.type, e.at) for e in entries] == [
        (date(2026, 12, 24), "early_close", time(12, 30)),
        (date(2026, 12, 25), "full_closure", None),
    ]


def test_lse_unrecognised_status_is_rejected_not_guessed():
    page = LSE_PAGE.replace("NON-trading day.", "Trading hours to be confirmed.")
    with pytest.raises(SourceError, match="cannot interpret status"):
        parse_lse(page, TODAY)


def test_asx_open_public_holiday_is_not_a_closure():
    entries = parse_asx(ASX_PAGE, TODAY)
    assert [(e.day, e.type, e.at) for e in entries] == [
        (date(2026, 4, 3), "full_closure", None),
        (date(2026, 12, 31), "early_close", time(14, 10)),
    ]


def test_asx_ambiguous_early_close_time_is_rejected():
    page = ASX_PAGE + "<p>[4] Normal trading ceases at 12:00 (Sydney time).</p>"
    with pytest.raises(SourceError, match="ambiguous"):
        parse_asx(page, TODAY)


def test_nse_holiday_with_special_session_is_unconfirmed():
    entries = parse_nse(
        nse_payload(
            [nse_row("26-Jan-2026", "Monday", "Republic Day"),
             nse_row("08-Nov-2026", "Sunday", "Diwali Laxmi Pujan", session="Muhurat Trading")]
        ),
        TODAY,
    )  # fmt: skip
    assert [(e.day, e.status) for e in entries] == [
        (date(2026, 1, 26), "confirmed"),
        (date(2026, 11, 8), "unconfirmed"),
    ]
    assert entries[1].note is not None and "Muhurat" in entries[1].note


@pytest.mark.parametrize(
    "payload",
    ["<html>Access denied</html>", json.dumps({"CM": []}), nse_payload([{"tradingDate": "x"}])],
    ids=["not-json", "empty", "malformed-row"],
)
def test_nse_invalid_response_is_rejected(payload):
    with pytest.raises(SourceError):
        parse_nse(payload, TODAY)


# --- comparison with the local file -----------------------------------------------------


def test_new_source_entries_are_added_and_rerun_is_idempotent():
    fetched = [entry(date(2026, 11, 26), "Thanksgiving Day")]
    merged, report = merge_market(market(), fetched)
    assert [e.day for e in report.added] == [date(2026, 11, 26)]
    again, report = merge_market(merged, fetched)
    assert again == merged and report.added == []


def test_conflicting_source_entry_never_overwrites_confirmed_local_entry():
    local = market((entry(date(2026, 12, 24), "Early close", "early_close", time(13, 0)),))
    fetched = [
        entry(date(2026, 12, 24), "Early close", "early_close", time(12, 0)),
        entry(date(2026, 12, 25), "Christmas Day"),
    ]
    merged, report = merge_market(local, fetched)
    assert merged == local  # nothing applied, not even the unrelated addition
    assert len(report.conflicts) == 1 and report.added == []


def test_same_day_different_type_is_a_conflict():
    local = market((entry(date(2026, 11, 27), "Day after Thanksgiving"),))
    fetched = [entry(date(2026, 11, 27), "Early close", "early_close", time(13, 0))]
    merged, report = merge_market(local, fetched)
    assert merged == local and len(report.conflicts) == 1


def test_entry_dropped_by_source_is_kept_and_reported():
    local = market((entry(date(2026, 7, 3), "Independence Day"),
                    entry(date(2026, 11, 26), "Thanksgiving Day")))  # fmt: skip
    fetched = [entry(date(2026, 1, 1), "New Year's Day"), entry(date(2026, 12, 25), "Christmas")]
    merged, report = merge_market(local, fetched)
    assert {e.day for e in merged.entries} >= {date(2026, 7, 3), date(2026, 11, 26)}
    assert {e.day for e in report.missing_from_source} == {date(2026, 7, 3), date(2026, 11, 26)}


def test_source_with_internally_conflicting_entries_is_not_applied():
    fetched = [entry(date(2026, 1, 1), "New Year's Day"), entry(date(2026, 1, 1), "Other")]
    merged, report = merge_market(market(), fetched)
    assert merged == market() and report.error is not None


# --- failures preserve the last known good calendar -------------------------------------


def write_calendar(path: Path, entries: tuple[HolidayEntry, ...]) -> str:
    text = render_exchange_calendar(ExchangeCalendar({"US": market(entries)}))
    path.write_text(text, encoding="utf-8")
    return text


def test_failed_request_keeps_local_entries_and_reports_failure():
    def offline(url: str) -> str:
        raise SourceError(f"request to {url} failed: network unreachable")

    current = ExchangeCalendar({"US": market((entry(date(2026, 11, 26), "Thanksgiving Day"),))})
    updated, reports = update_calendar(current, today=TODAY, fetcher=offline)
    assert updated == current
    assert reports[0].error is not None and "network unreachable" in reports[0].error


def test_updater_leaves_file_byte_identical_when_a_source_fails(tmp_path):
    path = tmp_path / "exchange_holidays.yaml"
    before = write_calendar(path, (entry(date(2026, 11, 26), "Thanksgiving Day"),))

    def offline(url: str) -> str:
        raise SourceError("network unreachable")

    assert main(["--calendar", str(path)], fetcher=offline, today=TODAY) == 1
    assert path.read_text(encoding="utf-8") == before


def test_updater_leaves_file_unchanged_when_source_page_changes_layout(tmp_path):
    path = tmp_path / "exchange_holidays.yaml"
    before = write_calendar(path, ())
    assert main(["--calendar", str(path)], fetcher=lambda url: "<html>new design</html>",
                today=TODAY) == 1  # fmt: skip
    assert path.read_text(encoding="utf-8") == before


def test_updater_writes_additions_and_a_report(tmp_path):
    path, report = tmp_path / "exchange_holidays.yaml", tmp_path / "report.md"
    write_calendar(path, ())

    assert main(["--calendar", str(path), "--report", str(report)],
                fetcher=lambda url: NYSE_PAGE, today=TODAY) == 0  # fmt: skip
    written = load_exchange_calendar(path)
    assert date(2026, 11, 27) in {e.day for e in written.markets["US"].entries}
    assert "Added: 2026-11-27 early_close 13:00" in report.read_text()


def test_invalid_local_file_is_not_replaced(tmp_path):
    path = tmp_path / "exchange_holidays.yaml"
    path.write_text("markets: {US: {exchange: NYSE}}", encoding="utf-8")
    assert main(["--calendar", str(path)], fetcher=lambda url: NYSE_PAGE, today=TODAY) == 2
    assert path.read_text(encoding="utf-8") == "markets: {US: {exchange: NYSE}}"


# --- local file validation --------------------------------------------------------------


def base_market(entries: list[dict[str, object]]) -> dict[str, object]:
    return {"markets": {"US": {"exchange": "NYSE", "timezone": "America/New_York",
                               "source": "NYSE", "source_url": "https://example.test",
                               "automated": True, "entries": entries}}}  # fmt: skip


@pytest.mark.parametrize(
    ("entries", "message"),
    [
        (
            [{"date": "2026-11-26", "type": "full_closure", "name": "A", "status": "confirmed",
              "retrieved": "2026-11-01"}] * 2,
            "duplicate",
        ),
        (
            [{"date": "2026-11-26", "type": "full_closure", "name": "A", "status": "confirmed",
              "retrieved": "2026-11-01"},
             {"date": "2026-11-26", "type": "early_close", "time": "13:00", "name": "B",
              "status": "confirmed", "retrieved": "2026-11-01"}],
            "both a full closure and a partial session",
        ),
        (
            [{"date": "2026-11-27", "type": "early_close", "name": "A", "status": "confirmed",
              "retrieved": "2026-11-01"}],
            "time must be",
        ),
        (
            [{"date": "2026-11-26", "type": "full_closure", "name": "A", "status": "maybe",
              "retrieved": "2026-11-01"}],
            "status",
        ),
        ([{"date": "2026-11-26", "type": "full_closure", "name": "A", "status": "confirmed"}],
         "retrieved"),
    ],
    ids=["duplicate", "conflict", "early-close-without-time", "bad-status", "no-retrieved"],
)  # fmt: skip
def test_invalid_local_entries_are_rejected(entries, message):
    with pytest.raises(ValueError, match=message):
        parse_exchange_calendar(base_market(entries))


def test_repository_calendar_is_valid_and_round_trips():
    calendar = load_exchange_calendar(Path("config/exchange_holidays.yaml"))
    import yaml

    assert parse_exchange_calendar(yaml.safe_load(render_exchange_calendar(calendar))) == calendar
