"""Strategy A forward observation (EXP-011): one read-only collection run. No orders.

    uv run python scripts/forward_observe.py

Each run:
1. refuses to run if any frozen Strategy A file differs from docs/research/strategy-a-freeze.json;
2. downloads recent XAUUSD M15/H1 and GBPUSD M15 bars read-only and merges them into
   data/forward/bars.local.json (git-ignored);
3. recomputes Strategy A on completed bars only and appends each new signal whose signal bar
   closed on or after 2026-11-15 23:00 UTC (trading day 2026-11-16) to
   data/forward/strategy_a_signals.jsonl;
4. for each logged signal whose entry moment is over 5 minutes old, downloads the bid/ask ticks
   from 60 s before to 301 s after the entry and appends the quote observation to
   data/forward/strategy_a_quotes.jsonl (quote movement, not execution slippage).

Safe to repeat: signals and observations are keyed and never duplicated or rewritten. Run it at
least daily (e.g. every 15 minutes from cron); a missed run is caught up by the next one, but
ticks must still be available from the broker.
"""

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import stdio_client

from trading.backtest.history_bars import load_history
from trading.market_data.history import download_rates
from trading.market_data.mcp_collector import (
    call_read_only,
    registered_server,
    server_parameters,
    verify_read_only,
)
from trading.market_data.mcp_export import BrokerClock
from trading.market_data.sessions import load_market_calendar
from trading.models import Direction
from trading.research.candidates import StrategyA
from trading.research.forward import (
    FORWARD_START,
    FREEZE_RECORD,
    completed,
    forward_signals,
    freeze_mismatches,
    merge_rows,
)
from trading.research.quotes import fetch_ticks, observe

DATA = Path("data/forward")
SERIES = (("XAUUSD", "M15"), ("XAUUSD", "H1"), ("GBPUSD", "M15"))
POINT = Decimal("0.01")
WARM_UP = timedelta(days=40)  # ADR(14) and ATR warm-up before the forward start


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _append(path: Path, rows: list[dict[str, Any]]) -> None:
    if rows:
        with path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")


async def collect(store: Path, start: datetime, now: datetime,
                  signals_path: Path, quotes_path: Path) -> dict[str, int]:  # fmt: skip
    data: dict[str, Any] = (json.loads(store.read_text(encoding="utf-8")) if store.exists()
                            else {"series": []})  # fmt: skip
    stored = {(s["symbol"], s["timeframe"]): s for s in data["series"]}
    params = server_parameters(registered_server())
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        await verify_read_only(session)
        status = await call_read_only(session, "terminal_status")
        terminal = status.get("terminal") or {}
        live = status.get("broker_offset_seconds")
        if terminal.get("connected") is not True or not status.get("broker_offset_confident"):
            raise SystemExit("MT5 terminal not connected or broker offset not confident; "
                             "no data written")  # fmt: skip
        assert isinstance(live, int)
        series = []
        for symbol, timeframe in SERIES:
            old = stored.get((symbol, timeframe), {"rates": []})
            last = max((r["time"] for r in old["rates"]), default=None)
            since = start - WARM_UP if last is None else (
                datetime.fromtimestamp(last, tz=UTC) - timedelta(days=2))  # fmt: skip
            fresh = await download_rates(session, symbol, timeframe, since, now)
            if fresh["problems"]:
                raise SystemExit(f"{symbol} {timeframe}: download problems {fresh['problems']}; "
                                 "no data written")  # fmt: skip
            fresh["rates"] = merge_rows(old["rates"], fresh["rates"])
            fresh["start"] = old.get("start", fresh["start"])
            series.append(fresh)
        data = {"downloaded_utc": now.isoformat(), "terminal_status": status, "series": series}
        store.write_text(json.dumps(data), encoding="utf-8")

        bars = load_history(store)
        m15 = completed(bars[("XAUUSD", "M15")], now)
        h1 = completed(bars[("XAUUSD", "H1")], now, timedelta(hours=1))
        calendar = load_market_calendar(Path("config/market_sessions.yaml"))
        strategy = StrategyA(m15, h1, calendar, POINT)
        current = forward_signals(strategy, start)
        logged = _read_jsonl(signals_path)
        keys = {(r["signal_close_utc"], r["direction"]) for r in logged if "direction" in r}
        new = []
        for record in current:
            if (record["signal_close_utc"], record["direction"]) in keys:
                continue
            close = datetime.fromisoformat(record["signal_close_utc"])
            new.append({**record, "recorded_utc": now.isoformat(),
                        "detection_lag_seconds": (now - close).total_seconds()})  # fmt: skip
        recomputed = {(r["signal_close_utc"], r["direction"]) for r in current}
        vanished = [{"type": "inconsistency", "recorded_utc": now.isoformat(),
                     "note": f"logged signal {k} is no longer produced from the stored bars"}
                    for k in sorted(keys - recomputed)]  # fmt: skip
        _append(signals_path, new + vanished)

        observed = {r["entry_time"] for r in _read_jsonl(quotes_path)}
        by_open = {b.open_time: b for b in m15}
        clock = BrokerClock("America/New_York", 7, live)
        quotes = []
        for record in _read_jsonl(signals_path):
            if "direction" not in record:
                continue
            entry = datetime.fromisoformat(record["entry_time_utc"])
            end = entry + timedelta(seconds=301)
            bar = by_open.get(entry)
            if entry.isoformat() in observed or end > now or bar is None:
                continue
            ticks = await fetch_ticks(session, clock, live, entry - timedelta(seconds=60), end)
            o = observe(ticks, entry, Direction(record["direction"]), Decimal(str(bar.open)),
                        bar.spread_points, POINT, window_end=end)  # fmt: skip
            row = {"entry_time": entry.isoformat(), "ticks": len(ticks),
                   "recorded_utc": now.isoformat()}  # fmt: skip
            row.update(o.as_dict() if o else {"observation": "no quote within 60 s of entry"})
            quotes.append(row)
        _append(quotes_path, quotes)
    return {"bars": len(m15), "new_signals": len(new), "inconsistencies": len(vanished),
            "quote_observations": len(quotes)}  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DATA)
    parser.add_argument("--start", default=FORWARD_START.isoformat(),
                        help="dry runs only, with a separate --data-dir")  # fmt: skip
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start)
    if start != FORWARD_START and args.data_dir.resolve() == DATA.resolve():
        raise SystemExit("a different --start is for dry runs: use a separate --data-dir")
    if not FREEZE_RECORD.exists():
        raise SystemExit(f"{FREEZE_RECORD} missing: Strategy A is not frozen")
    if changed := freeze_mismatches():
        raise SystemExit(f"frozen Strategy A files changed since the freeze: {changed}")
    args.data_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    summary = asyncio.run(collect(args.data_dir / "bars.local.json", start, now,
                                  args.data_dir / "strategy_a_signals.jsonl",
                                  args.data_dir / "strategy_a_quotes.jsonl"))  # fmt: skip
    print(json.dumps({"run_utc": now.isoformat(), **summary}))


if __name__ == "__main__":
    main()
