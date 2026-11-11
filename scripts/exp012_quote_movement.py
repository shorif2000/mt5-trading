"""EXP-012: quote movement at the modelled entry, from historical bid/ask ticks (registered
before running: docs/research/experiments/EXP-012-quote-movement-at-entry.md).

    uv run python scripts/exp012_quote_movement.py --require-clean

Read-only: ticks come from MT5 `get_ticks` through a session that refuses to start unless every
tool is annotated read-only; they are cached in a git-ignored local file. Quote movement is not
execution slippage: no order is sent.
"""

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from trading.backtest.provenance import build_manifest, code_state, file_sha256, unique_paths
from trading.models import Direction
from trading.research.breakeven import Tick, trade_from_manifest
from trading.research.candidates import StrategyA
from trading.research.inputs import load_inputs
from trading.research.levels import NEW_YORK
from trading.research.quotes import OFFSETS_SECONDS, fetch_ticks, observe

V1_MANIFEST = Path("reports/backtests/20261110T222100Z_7f525aace4.json")
SPEC = Path("docs/research/experiments/EXP-012-quote-movement-at-entry.md")
CACHE = Path("data/intrabar/exp012_ticks.local.json")
REPORTS = Path("reports/research")
FROM, TO = datetime(2025, 6, 14, tzinfo=UTC), datetime(2026, 10, 31, tzinfo=UTC)
BEFORE, AFTER = timedelta(seconds=60), timedelta(seconds=301)
POINT = Decimal("0.01")
QUANTILES = (0.10, 0.25, 0.50, 0.75, 0.90, 0.95)


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def session(moment: datetime) -> str:
    hour = moment.astimezone(NEW_YORK).hour
    if 8 <= hour < 17:
        return "New York (08-17 NY)"
    if 3 <= hour < 8:
        return "London (03-08 NY)"
    return "Asia (19-03 NY)"


async def download(entries: list[datetime]) -> dict[str, list[list[str]]]:
    from mcp import ClientSession  # noqa: PLC0415
    from mcp.client.stdio import stdio_client  # noqa: PLC0415

    from trading.market_data.mcp_collector import (  # noqa: PLC0415
        call_read_only,
        registered_server,
        server_parameters,
        verify_read_only,
    )
    from trading.market_data.mcp_export import BrokerClock  # noqa: PLC0415

    out: dict[str, list[list[str]]] = {}
    params = server_parameters(registered_server())
    async with stdio_client(params) as (read, write), ClientSession(read, write) as s:
        await s.initialize()
        await verify_read_only(s)
        status = await call_read_only(s, "terminal_status")
        live = status["broker_offset_seconds"]
        if not isinstance(live, int) or not status.get("broker_offset_confident"):
            raise SystemExit("broker offset not confident; ticks not downloaded")
        clock = BrokerClock("America/New_York", 7, live)
        for entry in entries:
            ticks = await fetch_ticks(s, clock, live, entry - BEFORE, entry + AFTER)
            out[_iso(entry)] = [[_iso(t.time), str(t.bid), str(t.ask)] for t in ticks]
    return out


def quantiles(values: list[float]) -> list[float] | None:
    if not values:
        return None
    v = sorted(values)
    return [v[int(q * (len(v) - 1))] for q in QUANTILES]


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"entries": len(rows)}
    for offset in OFFSETS_SECONDS:
        vals = [float(r["adverse"][offset]) for r in rows if r["adverse"].get(offset) is not None]
        out[f"adverse_{offset}s"] = quantiles(vals)
        out[f"share_adverse_over_7pts_{offset}s"] = (sum(v > 7 for v in vals) / len(vals)
                                                     if vals else None)  # fmt: skip
        out[f"share_adverse_over_40pts_{offset}s"] = (sum(v > 40 for v in vals) / len(vals)
                                                      if vals else None)  # fmt: skip
    for key in ("max_adverse_5s", "model_minus_first", "first_spread", "first_delay_s"):
        out[key] = quantiles([r[key] for r in rows if r[key] is not None])
    return out


def main() -> None:  # noqa: PLR0915
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-clean", action="store_true")
    parser.add_argument("--reports-dir", type=Path, default=REPORTS)
    args = parser.parse_args()
    started = datetime.now(UTC)
    code = code_state()
    if args.require_clean and code["dirty"]:
        raise SystemExit(f"uncommitted changes: {code['uncommitted_files']}")
    inp = load_inputs()
    v1 = json.loads(V1_MANIFEST.read_text())
    if file_sha256(inp.paths["history"]) != v1["inputs"]["history"]["sha256"]:
        raise SystemExit("history file differs from the one Version 1.0 used")
    by_open = {b.open_time: b for b in inp.m15}
    entries: list[tuple[str, datetime, Direction]] = []
    a = StrategyA(inp.m15, inp.h1, inp.calendar, POINT)
    for j, signal in sorted(a.signals.items()):
        entry = inp.m15[j].open_time + timedelta(minutes=15)
        if FROM <= entry < TO:
            entries.append(("Strategy A", entry, signal.setup.direction))
    for rows in v1["base_scenario_trades"].values():
        for row in rows:
            t = trade_from_manifest(row)
            if FROM <= t.entry_time < TO:
                entries.append(("Version 1.0", t.entry_time, t.direction))
    cache: dict[str, list[list[str]]] = (json.loads(CACHE.read_text()) if CACHE.exists()
                                         else {})  # fmt: skip
    missing = sorted({e for _, e, _ in entries if _iso(e) not in cache})
    if missing:
        cache.update(asyncio.run(download(missing)))
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache))
    rows: list[dict[str, Any]] = []
    unobserved: dict[str, int] = defaultdict(int)
    for source, entry, direction in entries:
        bar = by_open.get(entry)
        ticks = [Tick(datetime.fromisoformat(t.replace("Z", "+00:00")), Decimal(b), Decimal(k))
                 for t, b, k in cache.get(_iso(entry), [])]  # fmt: skip
        o = observe(ticks, entry, direction, Decimal(str(bar.open)), bar.spread_points, POINT,
                    window_end=entry + AFTER) if bar else None  # fmt: skip
        if o is None:
            unobserved[source] += 1
            continue
        rows.append({
            "source": source, "entry": entry, "direction": direction.value,
            "session": session(entry), "june_2025": entry < datetime(2025, 7, 1, tzinfo=UTC),
            "adverse": {k: v for k, v in o.adverse_points.items()},
            "max_adverse_5s": float(o.max_adverse_points_5s)
            if o.max_adverse_points_5s is not None else None,
            "model_minus_first": float(o.model_minus_first_points),
            "first_spread": float(o.first_spread_points),
            "first_delay_s": (o.first_tick_time - entry).total_seconds(),
        })  # fmt: skip
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[f"all ({r['source']})"].append(r)
        groups[f"{r['source']} / {r['session']}"].append(r)
        if r["june_2025"]:
            groups[f"{r['source']} / June 2025 (sparse ticks)"].append(r)
    results = {"entries": len(entries), "observed": len(rows), "unobserved": dict(unobserved),
               "groups": {k: summarise(v) for k, v in sorted(groups.items())}}  # fmt: skip
    report, manifest = unique_paths(args.reports_dir, f"EXP-012_{code['short_commit']}"
                                    f"{'-dirty' if code['dirty'] else ''}")  # fmt: skip
    m = build_manifest(code=code, started=started, command=sys.argv,
                       input_paths={**inp.paths, "version_1_0_manifest": V1_MANIFEST,
                                    "specification": SPEC},
                       parameters={"experiment": "EXP-012", "window": [_iso(FROM), _iso(TO)],
                                   "ticks_from_entry": [-60, 301], "offsets_s": OFFSETS_SECONDS,
                                   "assumed_entry_slippage_points": [0, 7, 40]},
                       manifest_path=manifest, results=results)  # fmt: skip
    manifest.write_text(json.dumps(m, indent=2, sort_keys=True), encoding="utf-8")
    report.write_text(render(m), encoding="utf-8")
    print(report)


def _fmt(q: list[float] | None) -> str:
    return "n/a" if q is None else " / ".join(f"{x:+.0f}" for x in q)


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.0%}"


def render(m: dict[str, Any]) -> str:
    r = m["results"]
    c = m["code"]
    w = [f"<!-- run {m['run_id']} -->", "# EXP-012: quote movement at the modelled entry", "",
         "Registered before running. Read-only ticks. **Quote movement is not execution "
         "slippage:** no order was sent, and real latency is unknown, so the offsets are "
         "illustrative.", "",
         f"- Run `{m['run_id']}`; code `{c['commit']}` on `{c['branch']}`; working tree "
         f"{'DIRTY' if c['dirty'] else 'clean'}",
         f"- Entries 2025-06-14 to 2026-10-30: {r['entries']}; observed {r['observed']}; "
         f"no quote within 60 s or no bar: {r['unobserved'] or 'none'}",
         "- Points: 1 point = USD 0.01 per ounce. Adverse = the executable quote (ask for a "
         "buy, bid for a sell) moved against the trade, relative to the first quote at or "
         "after the entry moment. Quantiles: 10 / 25 / 50 / 75 / 90 / 95%.", ""]  # fmt: skip
    w.append("## Adverse quote movement after the entry moment (points)\n")
    head = ["Group", "Entries", *[f"+{o}s" for o in (1.0, 2.0, 5.0, 60.0)],
            "Worst within 5 s", "Share > 7 pts at +1 s", "Share > 40 pts at +1 s"]  # fmt: skip
    rows = []
    for name, g in r["groups"].items():
        rows.append([name, str(g["entries"]), *[_fmt(g[f"adverse_{o}s"]) for o in
                                                ("1.0", "2.0", "5.0", "60.0")],
                     _fmt(g["max_adverse_5s"]), _pct(g["share_adverse_over_7pts_1.0s"]),
                     _pct(g["share_adverse_over_40pts_1.0s"])])  # fmt: skip
    w.append("| " + " | ".join(head) + " |\n|" + "---|" * len(head))
    w += ["| " + " | ".join(x) + " |" for x in rows]
    w.append("\n## Backtest entry model against the first real quote (points)\n")
    w.append(
        "Model = bar open (bid) + bar spread for a buy, bar open for a sell. Positive = the "
        "model entry was worse for the trade than the first real quote.\n"
    )
    head2 = ["Group", "Model − first quote", "First quote spread", "First quote delay (s)"]
    w.append("| " + " | ".join(head2) + " |\n|" + "---|" * len(head2))
    for name, g in r["groups"].items():
        delay = g["first_delay_s"]
        w.append(
            f"| {name} | {_fmt(g['model_minus_first'])} | {_fmt(g['first_spread'])} | "
            f"{'n/a' if delay is None else ' / '.join(f'{x:.1f}' for x in delay)} |"
        )
    w.append("\n## How to read this\n")
    w += [
        "- **Assumed entry slippage:** the base scenario assumes 7 points; the scenarios also "
        "use 0 and 40.",
        "- **Comparing:** the rows show how often the quote itself moved more than that within "
        "1 second of the modelled entry. This bounds part of the uncertainty. Real slippage also "
        "depends on order latency and broker execution, which only a separately authorised "
        "demo execution study could measure.",
        "- **No decision:** this changes no frozen experiment (EXP-011). Any new cost assumption "
        "would need a new registered experiment.",
    ]
    return "\n".join(w) + "\n"


if __name__ == "__main__":
    main()
