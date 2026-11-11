"""EXP-001: break-even exits on the fixed Version 1.0 entry list (registered before running:
docs/research/experiments/EXP-001-breakeven-exits.md).

    uv run python scripts/exp001_breakeven.py --require-clean

Offline. The only MT5 access is read-only tick download (`get_ticks`) for the sensitivity
analysis, through a session that refuses to start unless every tool is annotated read-only.
Ticks are cached in a git-ignored local file; `--no-ticks` skips the download (the tick
sensitivity is then reported as not run).
"""

import argparse
import asyncio
import dataclasses
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from trading.backtest.bars import Bar
from trading.backtest.engine import Backtest, ExecutionCosts
from trading.backtest.provenance import build_manifest, code_state, file_sha256, unique_paths
from trading.backtest.runner import PERIODS
from trading.models import Direction
from trading.research.breakeven import (
    VARIANTS,
    BreakEvenReplay,
    Mode,
    ReplayedTrade,
    Tick,
    TickOutcome,
    replay_period,
    resolve_from_ticks,
    trade_from_manifest,
)
from trading.research.inputs import load_inputs
from trading.research.stats import fmt, summarise
from trading.strategies.xauusd_m15_pullback import XauusdM15Pullback

V1_MANIFEST = Path("reports/backtests/20261110T222100Z_7f525aace4.json")
SPEC = Path("docs/research/experiments/EXP-001-breakeven-exits.md")
PROGRAMME = Path("docs/research/xauusd-research-programme.md")
TICK_CACHE = Path("data/intrabar/exp001_ticks.local.json")
TICKS_FROM = datetime(2025, 6, 14, tzinfo=UTC)  # first full day after the earliest tick
REPORTS = Path("reports/research")
LABEL = {"Training": "Training 2023-24", "Validation": "Validation 2025",
         "Out of sample": "2026 (development)"}  # fmt: skip
M15 = timedelta(minutes=15)


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


# --- ticks (read-only) ------------------------------------------------------------------


async def _download_ticks(bars: Sequence[datetime]) -> dict[str, list[list[Any]]]:
    from mcp import ClientSession  # noqa: PLC0415
    from mcp.client.stdio import stdio_client  # noqa: PLC0415

    from trading.market_data.mcp_collector import (  # noqa: PLC0415
        call_read_only,
        registered_server,
        server_parameters,
        verify_read_only,
    )
    from trading.market_data.mcp_export import BrokerClock  # noqa: PLC0415

    out: dict[str, list[list[Any]]] = {}
    params = server_parameters(registered_server())
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        await verify_read_only(session)
        status = await call_read_only(session, "terminal_status")
        live = status["broker_offset_seconds"]
        if not isinstance(live, int) or status.get("broker_offset_confident") is not True:
            raise SystemExit("broker offset not confident; ticks not downloaded")
        clock = BrokerClock("America/New_York", 7, live)
        for open_time in bars:
            end = open_time + M15
            # The server converts the request with today's offset; shift so that it asks for
            # the broker time that corresponds to ``open_time``.
            cursor = open_time + timedelta(seconds=clock.offset_at(open_time) - live)
            ticks: list[list[Any]] = []
            for _ in range(20):
                r = await call_read_only(session, "get_ticks", {
                    "symbol": "XAUUSD", "start": _iso(cursor), "count": 5000, "flags": "INFO"},
                    timeout=90)  # fmt: skip
                rows = r.get("ticks") or []
                if r.get("tool_error") or not rows:
                    break
                for row in rows:
                    ms = row["time_msc"]
                    utc = clock.utc(ms // 1000) + timedelta(milliseconds=ms % 1000)
                    if utc < end:
                        ticks.append([_iso(utc), row["bid"], row["ask"]])
                last_ms = rows[-1]["time_msc"]
                last_utc = clock.utc(last_ms // 1000) + timedelta(milliseconds=last_ms % 1000)
                if last_utc >= end or len(rows) < 5000:
                    break
                cursor = last_utc + timedelta(milliseconds=1)
                cursor += timedelta(seconds=clock.offset_at(last_utc) - live)
            out[_iso(open_time)] = ticks
    return out


def tick_resolver(cache: dict[str, list[list[Any]]]):  # noqa: ANN201
    parsed: dict[str, list[Tick]] = {}

    def resolve(bar: Bar, direction: Direction, fill: Decimal, stop: Decimal, target: Decimal,
                trigger: Decimal, level: Decimal) -> TickOutcome | None:  # fmt: skip
        key = _iso(bar.open_time)
        if key not in cache:
            return None
        if key not in parsed:
            parsed[key] = [
                Tick(datetime.fromisoformat(t.replace("Z", "+00:00")), Decimal(str(b)),
                     Decimal(str(a)))
                for t, b, a in cache[key]
            ]  # fmt: skip
        return resolve_from_ticks(parsed[key], bar, direction, stop, target, trigger, level)

    return resolve


# --- runs ---------------------------------------------------------------------------------


def make_engine(inp: Any, costs: ExecutionCosts, strategy: XauusdM15Pullback) -> Backtest:
    return Backtest(m15=inp.m15, h1=inp.h1, conversion_m15=inp.gbpusd_m15, spec=inp.spec,
                    conversion_spec=inp.conversion_spec, calendar=inp.calendar,
                    config=dataclasses.replace(inp.base_config, costs=costs),
                    margin_provider=None, strategy=strategy)  # fmt: skip


def summary(rows: list[ReplayedTrade], control: list[ReplayedTrade] | None) -> dict[str, Any]:
    records = [r.record for r in rows]
    s = summarise(records, Decimal(1000), events=len({r.event for r in rows}))
    s["break_even_exits"] = sum(r.break_even_exit for r in rows)
    s["break_even_exits_later_reaching_target"] = sum(bool(r.later_reached_target) for r in rows)
    s["ambiguous_trigger_bars"] = sum(r.ambiguous_trigger_bar for r in rows)
    s["tick_resolved"] = sum(r.tick_resolved is True for r in rows)
    s["tick_not_covered"] = sum(r.tick_resolved is False for r in rows)
    if control is not None:

        def cost(rs: list[ReplayedTrade]) -> float:
            return float(sum((r.record.spread_cost_gbp + r.record.exit_slippage_gbp
                              for r in rs), Decimal(0)))  # fmt: skip

        s["extra_spread_and_exit_slippage_gbp_vs_control"] = cost(rows) - cost(control)
    return s


def main() -> None:  # noqa: PLR0915
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-clean", action="store_true")
    parser.add_argument("--no-ticks", action="store_true")
    parser.add_argument("--reports-dir", type=Path, default=REPORTS)
    args = parser.parse_args()
    started = datetime.now(UTC)
    code = code_state()
    if args.require_clean and code["dirty"]:
        raise SystemExit(f"uncommitted changes: {code['uncommitted_files']}")
    v1 = json.loads(V1_MANIFEST.read_text())
    inp = load_inputs()
    if file_sha256(inp.paths["history"]) != v1["inputs"]["history"]["sha256"]:
        raise SystemExit("history file differs from the one Version 1.0 used")
    trades = {p: [trade_from_manifest(r) for r in v1["base_scenario_trades"][p]]
              for p, _, _ in PERIODS}  # fmt: skip
    strategy = XauusdM15Pullback(inp.m15, inp.h1, Decimal(str(inp.spec.tick_size)))
    base = inp.cost_model.base()
    grid = inp.cost_model.grid()

    # Primary: bar-close management, every cost scenario, variant and period.
    primary: dict[tuple[str, str, str], list[ReplayedTrade]] = {}
    for costs in grid:
        for rule in VARIANTS:
            for period, _, _ in PERIODS:
                replay = BreakEvenReplay(make_engine(inp, costs, strategy))
                primary[(costs.label, rule.name, period)] = replay_period(
                    replay, trades[period], rule
                )

    # Reconciliation gate: the base-scenario control must reproduce Version 1.0 exactly.
    mismatches = []
    for period, _, _ in PERIODS:
        got = primary[(base.label, VARIANTS[0].name, period)]
        for original, r in zip(trades[period], got, strict=True):
            rec = r.record
            if (rec.exit_time, rec.exit_reason, rec.net_gbp, rec.balance_after) != (
                original.exit_time, original.exit_reason, original.net_gbp,
                original.balance_after):  # fmt: skip
                mismatches.append(_iso(original.entry_time))
    if mismatches:
        raise SystemExit(f"control does not reproduce Version 1.0: {mismatches[:5]}")

    # Sensitivity (base scenario only): intrabar management.
    sensitivity: dict[tuple[str, str, str], list[ReplayedTrade]] = {}
    for mode in (Mode.INTRABAR_EXIT_FIRST, Mode.INTRABAR_NO_EXIT):
        for rule in VARIANTS[1:]:
            for period, _, _ in PERIODS:
                replay = BreakEvenReplay(make_engine(inp, base, strategy))
                sensitivity[(mode.value, rule.name, period)] = replay_period(
                    replay, trades[period], rule, mode
                )
    window = [t for p, _, _ in PERIODS for t in trades[p] if t.entry_time >= TICKS_FROM]
    tick_status = "not run (--no-ticks)"
    tick_rows: dict[str, dict[str, list[ReplayedTrade]]] = {}
    if not args.no_ticks:
        needed: set[datetime] = set()

        def collect(bar: Bar, *_: Any) -> None:
            needed.add(bar.open_time)
            return None

        for rule in VARIANTS[1:]:
            replay = BreakEvenReplay(make_engine(inp, base, strategy))
            replay_period(replay, window, rule, Mode.INTRABAR_TICKS, collect)  # type: ignore[arg-type]
        cache: dict[str, list[list[Any]]] = (
            json.loads(TICK_CACHE.read_text()) if TICK_CACHE.exists() else {})  # fmt: skip
        missing = sorted(t for t in needed if _iso(t) not in cache)
        if missing:
            cache.update(asyncio.run(_download_ticks(missing)))
            TICK_CACHE.parent.mkdir(parents=True, exist_ok=True)
            TICK_CACHE.write_text(json.dumps(cache))
        resolver = tick_resolver(cache)
        for rule in VARIANTS[1:]:
            tick_rows[rule.name] = {}
            for mode in (Mode.BAR_CLOSE, Mode.INTRABAR_EXIT_FIRST, Mode.INTRABAR_NO_EXIT,
                         Mode.INTRABAR_TICKS):  # fmt: skip
                replay = BreakEvenReplay(make_engine(inp, base, strategy))
                tick_rows[rule.name][mode.value] = replay_period(
                    replay, window, rule, mode, resolver if mode == Mode.INTRABAR_TICKS else None
                )
        tick_status = f"run: {len(needed)} ambiguous trigger bars needed ticks"

    # Summaries.
    results: dict[str, Any] = {"primary": {}, "sensitivity": {}, "tick_window": {}}
    for (label, rule, period), rows in primary.items():
        control = primary[(label, VARIANTS[0].name, period)]
        results["primary"].setdefault(label, {}).setdefault(rule, {})[period] = summary(
            rows, control
        )
    for (mode, rule, period), rows in sensitivity.items():
        results["sensitivity"].setdefault(mode, {}).setdefault(rule, {})[period] = summary(
            rows, None
        )
    for rule, modes in tick_rows.items():
        for mode, rows in modes.items():
            results["tick_window"].setdefault(rule, {})[mode] = summary(rows, None)

    # Pre-registered decision rule (section 3.4).
    decisions = {}
    non_zero = [
        c.label for c in grid if c.entry_points > 0 and c.stop_exit_points == base.stop_exit_points
    ]
    for rule in VARIANTS[1:]:

        def beats(label: str, rule_name: str = rule.name) -> bool:
            return all(
                results["primary"][label][rule_name][p]["fixed_risk"]["gross_r_per_trade"]
                > results["primary"][label][VARIANTS[0].name][p]["fixed_risk"]["gross_r_per_trade"]
                for p, _, _ in PERIODS)  # fmt: skip

        screen = beats(base.label) and all(beats(label) for label in non_zero)
        decisions[rule.name] = {
            "gross_beats_control_in_all_periods_base": beats(base.label),
            "also_in_non_zero_entry_scenarios": all(beats(label) for label in non_zero),
            "passes_historical_screen": screen,
            "outcome": ("passes the historical screen; would still need the forward hold-out, "
                        "and is not adopted because Version 1.0 has no gross edge")
            if screen else "does not pass the historical screen",
        }  # fmt: skip

    report_path, manifest_path = unique_paths(args.reports_dir, f"EXP-001_{code['short_commit']}"
                                              f"{'-dirty' if code['dirty'] else ''}")  # fmt: skip
    parameters = {
        "experiment": "EXP-001", "specification": str(SPEC),
        "specification_sha256": file_sha256(SPEC), "programme_sha256": file_sha256(PROGRAMME),
        "version_1_0_run": v1["run_id"], "variants": [dataclasses.asdict(v) for v in VARIANTS],
        "primary_mode": Mode.BAR_CLOSE.value, "cost_scenarios": [c.label for c in grid],
        "base_scenario": base.label, "tick_window_from": _iso(TICKS_FROM),
        "tick_sensitivity": tick_status,
        "cost_status": {
            "spread": "measured (historical bar spread)",
            "stop_slippage": "measured percentiles of the account's stop fills",
            "entry_and_market_exit_slippage": "assumed scenarios (0, 7, 40 points)",
            "take_profit_slippage": "measured (0)", "commission": "measured (£0)",
            "swap": "0: no position held overnight",
        },
    }  # fmt: skip
    manifest = build_manifest(
        code=code, started=started, command=sys.argv,
        input_paths={**inp.paths, "version_1_0_manifest": V1_MANIFEST, "specification": SPEC},
        parameters=parameters, manifest_path=manifest_path,
        results={"reconciliation": "base-scenario control reproduces all "
                 f"{sum(len(v) for v in trades.values())} Version 1.0 trades exactly",
                 "decisions": decisions, **results},
    )  # fmt: skip
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    report_path.write_text(render(manifest, base.label, grid), encoding="utf-8")
    print(f"report {report_path}\nmanifest {manifest_path}")


# --- report ---------------------------------------------------------------------------------


def _table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    return "\n".join(out + ["| " + " | ".join(r) + " |" for r in rows])


def render(m: dict[str, Any], base: str, grid: Sequence[ExecutionCosts]) -> str:  # noqa: PLR0915
    res = m["results"]
    names = [v.name for v in VARIANTS]
    w: list[str] = []
    w.append(
        f"<!-- run {m['run_id']} -->\n# EXP-001: break-even exits on the Version 1.0 entries\n"
    )
    w.append(
        "Research only. Registered before running "
        "(`docs/research/experiments/EXP-001-breakeven-exits.md`). No orders; MT5 was "
        "used read-only for ticks only.\n"
    )
    c = m["code"]
    w.append(f"- Run `{m['run_id']}`; command `{m['command']}`")
    w.append(
        f"- Code: `{c['commit']}` on `{c['branch']}`; working tree "
        f"{'DIRTY: ' + ', '.join(c['uncommitted_files']) if c['dirty'] else 'clean'}"
    )
    for name, info in m["inputs"].items():
        w.append(f"- Input `{name}`: `{info['path']}` sha256 `{info['sha256'][:16]}…`")
    p = m["parameters"]
    w.append(
        f"- Specification sha256 `{p['specification_sha256'][:16]}…`; Version 1.0 run "
        f"`{p['version_1_0_run']}`"
    )
    w.append(
        f"- **Reconciliation: {res['reconciliation']}** (exit time, exit reason, net GBP "
        "and running balance)."
    )
    w.append(f"- Tick sensitivity: {p['tick_sensitivity']}.\n")
    w.append(
        "**Costs.** Spread and stop slippage are measured; entry and market-exit slippage "
        "are assumed scenarios; commission £0 and take-profit slippage 0 are measured; swap "
        "is 0 because no position is held overnight. R = net ÷ the trade's estimated loss "
        "at sizing (fixed-risk ledger, £20 per R); compounding = Version 1.0 volumes on a "
        "£1,000 balance per period. 2026 is development evidence.\n"
    )

    w.append("## Primary results (bar-close management, base cost scenario)\n")
    rows = []
    for period, _, _ in PERIODS:
        for name in names:
            s = res["primary"][base][name][period]
            f, g = s["fixed_risk"], s["compounding"]
            ci = f["net_r_ci95"]
            rows.append([LABEL[period], name, str(s["trades"]), str(s["events"]),
                         f"{s['win_rate']:.1%}", fmt(f["average_win_r"], 2),
                         fmt(f["average_loss_r"], 2), fmt(f["gross_r_per_trade"]),
                         f"{fmt(f['net_r_per_trade'])} [{ci[0]:+.3f}, {ci[1]:+.3f}]",
                         fmt(f["profit_factor"], 2, False), fmt(f["max_drawdown_r"], 1, False),
                         f"£{g['net_gbp']:,.2f}", f"{g['max_drawdown_percent']:.1f}%",
                         f"£{g['average_win_gbp'] or 0:,.2f} / "
                         f"£{g['average_loss_gbp'] or 0:,.2f}"])  # fmt: skip
    w.append(_table(["Period", "Variant", "Trades", "Events", "Win rate", "Avg win R",
                     "Avg loss R", "Gross R/trade", "Net R/trade [95% CI]", "PF (R)",
                     "Max DD (R)", "Compounding net", "Compounding max DD",
                     "Avg win / loss (GBP)"], rows))  # fmt: skip
    w.append("\n### Break-even exits, extra costs and ambiguous bars (base scenario)\n")
    rows = []
    for period, _, _ in PERIODS:
        for name in names[1:]:
            s = res["primary"][base][name][period]
            rows.append([LABEL[period], name, str(s["break_even_exits"]),
                         str(s["break_even_exits_later_reaching_target"]),
                         f"£{s['extra_spread_and_exit_slippage_gbp_vs_control']:+,.2f}",
                         fmt(s["cost_r_per_trade"]), str(s["ambiguous_trigger_bars"])])  # fmt: skip
    w.append(_table(["Period", "Variant", "Break-even exits",
                     "…later reached the original target", "Extra spread + exit slippage vs "
                     "control", "Cost R/trade", "Ambiguous trigger bars"], rows))  # fmt: skip
    w.append(
        "\n“Later reached the original target”: after the break-even exit, the original "
        "stop and target were replayed with Version 1.0 rules (stop first within a bar) "
        "until the forced close.\n"
    )
    w.append("### Exit mix (base scenario, all periods)\n")
    rows = []
    for name in names:
        mix: dict[str, int] = {}
        for period, _, _ in PERIODS:
            for k, v in res["primary"][base][name][period]["exits"].items():
                mix[k] = mix.get(k, 0) + v
        rows.append(
            [name, "; ".join(f"{k}: {v}" for k, v in sorted(mix.items(), key=lambda kv: -kv[1]))]
        )
    w.append(_table(["Variant", "Exits"], rows))

    w.append("\n## Cost scenarios (fixed list; net R per trade, Training / Validation / 2026)\n")
    rows = []
    for costs in grid:
        cells = []
        for name in names:
            vals = [
                res["primary"][costs.label][name][p]["fixed_risk"]["net_r_per_trade"]
                for p, _, _ in PERIODS
            ]
            cells.append(" / ".join(fmt(v, 3) for v in vals))
        rows.append([costs.label + (" **(base)**" if costs.label == base else ""), *cells])
    w.append(_table(["Scenario", *names], rows))
    w.append("\nGross R per trade (before spread and slippage), same layout:\n")
    rows = []
    for costs in grid:
        cells = [
            " / ".join(
                fmt(res["primary"][costs.label][n][p]["fixed_risk"]["gross_r_per_trade"], 3)
                for p, _, _ in PERIODS
            )
            for n in names
        ]
        rows.append([costs.label, *cells])
    w.append(_table(["Scenario", *names], rows))

    w.append("\n## Sensitivity: intrabar management (not the primary result)\n")
    w.append(
        "The stop moves the moment the trigger is touched. Where the trigger bar also "
        "touches the break-even level, M15 cannot order the two; both orderings are shown. "
        "Net R per trade, base scenario.\n"
    )
    rows = []
    for name in names[1:]:
        for period, _, _ in PERIODS:
            prim = res["primary"][base][name][period]["fixed_risk"]["net_r_per_trade"]
            a = res["sensitivity"][Mode.INTRABAR_EXIT_FIRST.value][name][period]
            b = res["sensitivity"][Mode.INTRABAR_NO_EXIT.value][name][period]
            rows.append([name, LABEL[period], fmt(prim),
                         fmt(a["fixed_risk"]["net_r_per_trade"]),
                         fmt(b["fixed_risk"]["net_r_per_trade"]),
                         str(a["ambiguous_trigger_bars"])])  # fmt: skip
    w.append(_table(["Variant", "Period", "Primary (bar close)", "Intrabar: exit first",
                     "Intrabar: no exit", "Ambiguous trigger bars"], rows))  # fmt: skip
    if res["tick_window"]:
        w.append(f"\n### Tick-resolved trigger bars (trades from {p['tick_window_from'][:10]})\n")
        rows = []
        for name in names[1:]:
            modes = res["tick_window"][name]
            t = modes[Mode.INTRABAR_TICKS.value]
            rows.append([name, str(t["trades"]),
                         *[fmt(modes[mo.value]["fixed_risk"]["net_r_per_trade"]) for mo in (
                             Mode.BAR_CLOSE, Mode.INTRABAR_EXIT_FIRST, Mode.INTRABAR_NO_EXIT,
                             Mode.INTRABAR_TICKS)],
                         f"{t['tick_resolved']} / {t['tick_not_covered']}"])  # fmt: skip
        w.append(_table(["Variant", "Trades", "Primary (bar close)", "Intrabar exit first",
                         "Intrabar no exit", "Intrabar from ticks",
                         "Bars resolved / not covered (fell back to exit first)"],
                        rows))  # fmt: skip

    w.append("\n## Pre-registered decision rule\n")
    for name, d in res["decisions"].items():
        w.append(
            f"- **{name}**: gross R/trade above the control in all three periods (base): "
            f"{'yes' if d['gross_beats_control_in_all_periods_base'] else 'no'}; also in "
            f"the 7- and 40-point entry scenarios: "
            f"{'yes' if d['also_in_non_zero_entry_scenarios'] else 'no'} → {d['outcome']}."
        )
    w.append(
        "\nNo variant is selected from these periods. Version 1.0 has no gross edge "
        "(diagnostic review), so no break-even rule is adopted whatever the screen says.\n"
    )
    w.append("## Limitations\n")
    w.append(
        "- Fixed entry list: trades Version 1.0 skipped while a position was open stay "
        "skipped even when a break-even exit would have freed the slot."
    )
    w.append(
        "- Non-base scenarios replay the base list without re-sizing; only the base "
        "control reconciles with a Version 1.0 run."
    )
    w.append("- One spread value per M15 bar; stop first when a bar touches stop and target.")
    w.append("- Ticks exist only from 2025-06-13; Training cannot be tick-resolved.")
    w.append("- The trigger bar's own exit uses Version 1.0's stop-first convention.")
    w.append("- Not news-filtered (Version 1.0 has no calendar).")
    return "\n".join(w) + "\n"


if __name__ == "__main__":
    main()
