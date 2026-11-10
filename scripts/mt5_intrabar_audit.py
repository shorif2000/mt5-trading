"""Read-only audit of XAUUSD M1 and tick history depth, for intrabar break-even research.

Opens one session with the registered MT5 MCP server, refuses to run unless every advertised
tool is annotated read-only (``verify_read_only``), and calls only allow-listed read tools:
terminal_status, get_ticks and get_rates. Nothing is sent to the market.

    uv run python scripts/mt5_intrabar_audit.py            # download, then summarise
    uv run python scripts/mt5_intrabar_audit.py --summarise-only

Raw results go to a git-ignored ``*.local.json`` file; the summary is printed as JSON.

Time caveat: the server converts request limits and ``*_utc`` fields with the broker offset in
force *now*. For dates under the other daylight-saving offset those labels are one hour off.
The coverage sampling only compares a tick with its own request (same conversion), and the M1
bars are re-converted from raw broker time by the project's DST-aware loader.
"""

import argparse
import asyncio
import json
import statistics
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import stdio_client

from trading.backtest.history_bars import coverage, load_history
from trading.market_data.history import download_rates
from trading.market_data.mcp_collector import (
    call_read_only,
    registered_server,
    server_parameters,
    verify_read_only,
)
from trading.market_data.sessions import load_market_calendar

OUTPUT = Path("data/intrabar/xauusd_intrabar_audit.local.json")
M1_OUTPUT = Path("data/intrabar/xauusd_m1.local.json")
SYMBOL = "XAUUSD"
# Sample times (UTC) inside gold's trading hours on every weekday: Asia, London, New York.
SAMPLE_TIMES = ((1, 30), (8, 0), (14, 30))
TICK_SAMPLE_START = date(2025, 6, 9)  # the week of the earliest tick found by probing
DENSITY_SAMPLES = (
    datetime(2025, 7, 15, 14, 30, tzinfo=UTC),
    datetime(2026, 3, 17, 14, 30, tzinfo=UTC),
    datetime(2026, 10, 20, 14, 30, tzinfo=UTC),
)


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def _tick_time(tick: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(tick["time_utc"].replace("Z", "+00:00"))


async def _audit(now: datetime) -> dict[str, Any]:
    params = server_parameters(registered_server())
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        await verify_read_only(session)
        status = await call_read_only(session, "terminal_status")
        earliest = await call_read_only(
            session, "get_ticks",
            {"symbol": SYMBOL, "start": "2015-01-01T00:00:00Z", "count": 1, "flags": "INFO"},
            timeout=120,
        )  # fmt: skip
        samples = []
        day = TICK_SAMPLE_START
        while day <= now.date():
            if day.weekday() < 5:
                for hour, minute in SAMPLE_TIMES:
                    at = datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)
                    if at > now - timedelta(minutes=10):
                        continue
                    r = await call_read_only(
                        session, "get_ticks",
                        {"symbol": SYMBOL, "start": _iso(at), "count": 1, "flags": "INFO"},
                        timeout=60,
                    )  # fmt: skip
                    ticks = r.get("ticks") or []
                    samples.append({
                        "requested_utc": _iso(at),
                        "error": r.get("tool_error"),
                        "first_tick": ticks[0] if ticks else None,
                    })  # fmt: skip
            day += timedelta(days=1)
        density = []
        for at in DENSITY_SAMPLES:
            r = await call_read_only(
                session, "get_ticks",
                {"symbol": SYMBOL, "start": _iso(at), "count": 5000, "flags": "INFO"},
                timeout=120,
            )  # fmt: skip
            ticks = r.get("ticks") or []
            density.append({
                "requested_utc": _iso(at), "error": r.get("tool_error"), "count": len(ticks),
                "first_utc": ticks[0]["time_utc"] if ticks else None,
                "last_utc": ticks[-1]["time_utc"] if ticks else None,
                "zero_bid_or_ask": sum(1 for t in ticks if not t.get("bid") or not t.get("ask")),
                "spread_points_median": statistics.median(
                    round((t["ask"] - t["bid"]) * 100) for t in ticks) if ticks else None,
            })  # fmt: skip
        m1 = await download_rates(session, SYMBOL, "M1", now - timedelta(days=130), now)
    return {
        "audited_utc": _iso(now),
        "terminal_status": status,
        "earliest_tick_probe": earliest,
        "tick_samples": samples,
        "tick_density": density,
        "m1": m1,
    }


def summarise(raw: dict[str, Any]) -> dict[str, Any]:
    samples = raw["tick_samples"]
    hits, late, errors, missing_days = 0, 0, 0, set()
    for s in samples:
        if s["error"]:
            errors += 1
            continue
        tick = s["first_tick"]
        requested = datetime.fromisoformat(s["requested_utc"].replace("Z", "+00:00"))
        if tick and _tick_time(tick) - requested <= timedelta(minutes=2):
            hits += 1
        else:
            late += 1
            missing_days.add(s["requested_utc"][:10])
    # M1: write in the history file format so the existing loader and coverage check apply.
    M1_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    M1_OUTPUT.write_text(json.dumps({"terminal_status": raw["terminal_status"],
                                     "series": [raw["m1"]]}), encoding="utf-8")  # fmt: skip
    summary: dict[str, Any] = {
        "audited_utc": raw["audited_utc"],
        "earliest_tick": (raw["earliest_tick_probe"].get("ticks") or [{}])[0].get("time_utc"),
        "tick_samples": len(samples),
        "tick_sample_hits_within_2_minutes": hits,
        "tick_sample_no_tick_within_2_minutes": late,
        "tick_sample_errors": errors,
        "tick_sample_dates_without_nearby_tick": sorted(missing_days),
        "tick_density": raw["tick_density"],
        "m1_problems": raw["m1"]["problems"],
    }
    if not raw["m1"]["problems"]:
        bars = load_history(M1_OUTPUT)[(SYMBOL, "M1")]
        calendar = load_market_calendar(Path("config/market_sessions.yaml"))
        c = coverage(SYMBOL, "M1", bars, calendar)
        summary["m1"] = {
            "bars": c.bars,
            "first_utc": c.first.isoformat() if c.first else None,
            "last_utc": c.last.isoformat() if c.last else None,
            "gaps_over_15_minutes_in_scheduled_hours": [
                (a.isoformat(), b.isoformat()) for a, b in c.gaps
            ],
        }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summarise-only", action="store_true")
    args = parser.parse_args()
    if not args.summarise_only:
        raw = asyncio.run(_audit(datetime.now(UTC).replace(second=0, microsecond=0)))
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(raw), encoding="utf-8")
    raw = json.loads(OUTPUT.read_text(encoding="utf-8"))
    print(json.dumps(summarise(raw), indent=2))


if __name__ == "__main__":
    main()
