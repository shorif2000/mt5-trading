"""Weekly Strategy A forward-observation report (EXP-011). Evidence only.

    uv run python scripts/strategy_a_monitor.py

Reads the forward bars, signal log and quote log written by scripts/forward_observe.py,
replays the frozen Strategy A arms over the forward window with the Version 1.0 engine (broker
margin read-only from MT5 calc_margin; nothing is sent), and writes a new report under
reports/forward/. It states whether each arm is ready for the pre-registered evaluation and
never makes a buy or sell recommendation.
"""

import argparse
import dataclasses
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from trading.backtest.history_bars import coverage
from trading.backtest.provenance import build_manifest, code_state, unique_paths
from trading.backtest.report import session_of
from trading.market_data.mcp_collector import MarginSession
from trading.research.candidate_engine import CandidateBacktest, CandidateOptions, with_period
from trading.research.candidates import StrategyA
from trading.research.forward import (
    FORWARD_START,
    FREEZE_RECORD,
    completed,
    evaluate,
    forward_signals,
    freeze_mismatches,
    readiness,
)
from trading.research.inputs import load_inputs
from trading.research.levels import trading_day
from trading.research.news import NewsFilter, load_calendar
from trading.research.stats import r_gross, r_net, summarise

DATA = Path("data/forward")
REPORTS = Path("reports/forward")
CALENDAR = Path("config/economic_calendar.yaml")
KINDS = ["fomc_statement", "cpi", "employment_situation"]
ARMS = {"no cost floor": None, "0.10R cost floor": Decimal("0.10")}
POINT = Decimal("0.01")
NO_RECOMMENDATION = ("**This report makes no buy or sell recommendation.** It reports evidence "
                     "and whether the pre-registered evaluation may be carried out.")  # fmt: skip


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]


def _q(values: list[float]) -> str:
    if not values:
        return "n/a"
    v = sorted(values)
    pick = [v[int(p * (len(v) - 1))] for p in (0.1, 0.5, 0.9)]
    return " / ".join(f"{x:.2f}" for x in pick)


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def _event_label(e: Any) -> str:
    return f"{e.kind} ({e.status}{', no time' if e.release_time is None else ''})"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    return "\n".join(out + ["| " + " | ".join(r) + " |" for r in rows])


def main() -> None:  # noqa: PLR0915
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DATA)
    parser.add_argument("--reports-dir", type=Path, default=REPORTS)
    parser.add_argument("--as-of", help="UTC moment (default: now)")
    args = parser.parse_args()
    if changed := freeze_mismatches():
        raise SystemExit(f"frozen Strategy A files changed since the freeze: {changed}")
    freeze = json.loads(FREEZE_RECORD.read_text(encoding="utf-8"))
    as_of = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(UTC)
    started = datetime.now(UTC)
    code = code_state()
    store = args.data_dir / "bars.local.json"
    if not store.exists():
        raise SystemExit(f"{store} missing: run scripts/forward_observe.py first")
    inp = load_inputs(history=store)
    m15 = completed(inp.m15, as_of)
    h1 = completed(inp.h1, as_of, timedelta(hours=1))
    strategy = StrategyA(m15, h1, inp.calendar, POINT)
    end = (m15[-1].open_time + timedelta(minutes=15)) if m15 else FORWARD_START
    window_end = max(end, FORWARD_START)
    logged = [r for r in _jsonl(args.data_dir / "strategy_a_signals.jsonl") if "direction" in r]
    inconsistencies = [r for r in _jsonl(args.data_dir / "strategy_a_signals.jsonl")
                       if r.get("type") == "inconsistency"]  # fmt: skip
    quotes = _jsonl(args.data_dir / "strategy_a_quotes.jsonl")
    recomputed = forward_signals(strategy)
    calendar = load_calendar(CALENDAR)
    news = NewsFilter(calendar, KINDS)
    grid = inp.cost_model.grid()
    base = inp.cost_model.base()
    stress = next(c for c in grid if c.entry_points == 40
                  and c.stop_exit_points == base.stop_exit_points)  # fmt: skip

    def run(costs: Any, floor: Decimal | None, fixed: bool, provider: Any) -> Any:
        config = with_period(dataclasses.replace(inp.base_config, costs=costs),
                             FORWARD_START, window_end)  # fmt: skip
        engine = CandidateBacktest(
            candidate=strategy, options=CandidateOptions(cost_floor=floor, news=news,
                                                         fixed_risk=fixed),
            m15=m15, h1=h1, conversion_m15=inp.gbpusd_m15, spec=inp.spec,
            conversion_spec=inp.conversion_spec, calendar=inp.calendar, config=config,
            margin_provider=provider)  # fmt: skip
        return engine.run()

    arms: dict[str, Any] = {}
    with MarginSession() as session:

        def provider(side: str, volume: Decimal, price: Decimal) -> dict[str, Any]:
            return session.margin(symbol="XAUUSD", side=side, volume=float(volume),
                                  price=float(price))  # type: ignore[arg-type]  # fmt: skip

        for arm, floor in ARMS.items():
            fixed = run(base, floor, True, provider)
            compounding = run(base, floor, False, provider)
            stressed = run(stress, floor, True, provider)
            events = len({(s.direction, s.pullback_event) for s in fixed.signals})
            cut = freeze["volatility_cutoffs"][arm]
            terciles: dict[str, list[float]] = defaultdict(list)
            for t in fixed.trades:
                ratio = strategy.levels.adr_ratio(trading_day(t.entry_time))
                if ratio is not None:
                    name = "low" if ratio < cut[0] else "normal" if ratio < cut[1] else "high"
                    terciles[name].append(r_net(t))
            status = readiness(events, as_of)
            evaluation = (evaluate([r_net(t) for t in fixed.trades],
                                   [r_gross(t) for t in fixed.trades],
                                   [r_net(t) for t in stressed.trades], terciles)
                          if status == "READY FOR EVALUATION" else None)  # fmt: skip
            by_group: dict[str, list[float]] = defaultdict(list)
            for t in fixed.trades:
                by_group[f"{t.entry_time.year} / {session_of(t)}"].append(r_net(t))
            arms[arm] = {
                "readiness": status,
                "evaluation": evaluation,
                "events": events,
                "fixed": summarise(fixed.trades, Decimal(1000), events=events),
                "compounding": summarise(compounding.trades, Decimal(1000), events=events)[
                    "compounding"],
                "stress_net_r": statistics.fmean([r_net(t) for t in stressed.trades])
                if stressed.trades else None,
                "rejections": dict(Counter(s.reasons[0] for s in fixed.signals
                                           if s.outcome.value != "executable").most_common()),
                "by_year_and_session": {k: [len(v), statistics.fmean(v), sum(v)]
                                        for k, v in sorted(by_group.items())},
                "stop_usd_quantiles": _q([float(abs(t.quoted_entry - t.stop))
                                          for t in fixed.trades]),
            }  # fmt: skip

    # Cost evidence for every logged signal: entry-bar spread and estimated cost / stop.
    by_open = {b.open_time: b for b in m15}
    spreads, cost_r = [], []
    for r in logged:
        bar = by_open.get(datetime.fromisoformat(r["entry_time_utc"]))
        if bar is None:
            continue
        bid = Decimal(str(bar.open))
        entry = bid + bar.spread_points * POINT if r["direction"] == "buy" else bid
        risk = abs(entry - Decimal(r["stop"]))
        spreads.append(bar.spread_points)
        if risk:
            cost_r.append(float((bar.spread_points + 47) * POINT / risk))
    observed = [q for q in quotes if "adverse_points" in q]
    quote_stats = {str(k): _q([float(q["adverse_points"][str(k)]) for q in observed
                               if q["adverse_points"].get(str(k)) is not None])
                   for k in (1.0, 2.0, 5.0)}  # fmt: skip
    model_gap = _q([float(q["model_minus_first_points"]) for q in observed])

    # Data completeness and calendar coverage over the forward window.
    window = [b for b in m15 if FORWARD_START <= b.open_time < window_end]
    gaps = coverage("XAUUSD", "M15", window, inp.calendar).gaps if window else ()
    days = sorted({trading_day(b.open_time) for b in window})
    uncovered = []
    for d in days:
        reason = news.check(datetime(d.year, d.month, d.day, 3, tzinfo=UTC))
        if reason and reason.startswith("economic calendar unavailable"):
            uncovered.append(str(d))
    in_window = [e for e in calendar.events
                 if days and days[0] <= e.day <= days[-1]]  # fmt: skip
    published_to = {c.kind: str(c.end) for c in calendar.coverage if "publication" in c.note
                    or "every meeting" in c.note}  # fmt: skip
    lags = [r["detection_lag_seconds"] for r in logged]
    key = {(r["signal_close_utc"], r["direction"]) for r in logged}
    recomputed_keys = {(r["signal_close_utc"], r["direction"]) for r in recomputed}

    results = {
        "as_of_utc": as_of.isoformat(), "forward_start_utc": FORWARD_START.isoformat(),
        "window_end_utc": window_end.isoformat(), "arms": arms,
        "signals_logged": len(logged), "signals_recomputed": len(recomputed),
        "log_matches_recomputation": key == recomputed_keys,
        "inconsistencies": len(inconsistencies),
        "entry_bar_spread_points": _q([float(x) for x in spreads]),
        "estimated_cost_over_stop": _q(cost_r),
        "share_within_cost_floor": (sum(x <= 0.10 for x in cost_r) / len(cost_r))
        if cost_r else None,
        "quote_observations": len(observed), "no_quote": len(quotes) - len(observed),
        "adverse_quote_points_10_50_90": quote_stats, "model_minus_first_quote_points": model_gap,
        "detection_lag_seconds": _q([float(x) for x in lags]),
        "bars_in_window": len(window), "gaps_over_15_min": len(gaps),
        "calendar_days_uncovered": uncovered,
        "calendar_events_in_window": dict(Counter(_event_label(e) for e in in_window)),
        "calendar_published_coverage_to": published_to,
    }  # fmt: skip
    name = f"strategy_a_monitor_{as_of:%Y-%m-%d}_{code['short_commit']}"
    report, manifest = unique_paths(args.reports_dir, name)
    paths = {"forward_bars": store, "calendar": CALENDAR, "freeze_record": FREEZE_RECORD}
    for key_name, file in (("signals", "strategy_a_signals.jsonl"),
                           ("quotes", "strategy_a_quotes.jsonl")):  # fmt: skip
        if (args.data_dir / file).exists():
            paths[key_name] = args.data_dir / file
    parameters = {"experiment": "EXP-011", "freeze": freeze["frozen_at"], "news_kinds": KINDS,
                  "base_scenario": base.label, "stress_scenario": stress.label}  # fmt: skip
    m = build_manifest(code=code, started=started, command=sys.argv, input_paths=paths,
                       parameters=parameters, manifest_path=manifest, results=results)  # fmt: skip
    manifest.write_text(json.dumps(m, indent=2, sort_keys=True), encoding="utf-8")
    report.write_text(render(m), encoding="utf-8")
    print(report)


def render(m: dict[str, Any]) -> str:
    r = m["results"]
    w = [f"<!-- run {m['run_id']} -->",
         f"# Strategy A forward observation: monitoring report ({r['as_of_utc'][:10]})", "",
         NO_RECOMMENDATION, "",
         f"- Experiment EXP-011; forward data from {r['forward_start_utc']} to "
         f"{r['window_end_utc']} (completed bars only). Frozen specification "
         f"`{m['parameters']['freeze']}`, unchanged (checked before running).",
         f"- Code `{m['code']['commit']}`; news filter: FOMC, CPI, Employment Situation.",
         "- Paper replay only: no orders. Margin read-only (MT5 calc_margin).", ""]  # fmt: skip
    w.append("## Readiness\n")
    w.append(_table(["Arm", "Events", "Status"],
                    [[a, str(v["events"]), v["readiness"]]
                     for a, v in r["arms"].items()]))  # fmt: skip
    for arm, v in r["arms"].items():
        if v["evaluation"]:
            e = v["evaluation"]
            w.append(f"\n**{arm}: pre-registered evaluation — {e['outcome']}** "
                     f"(net R {e['net_r'][0]:+.3f}, {e['ci_level']:.1%} interval "
                     f"[{e['net_r'][1]:+.3f}, {e['net_r'][2]:+.3f}]; "
                     f"checks {e['checks']})")  # fmt: skip
    w.append("\n## Results so far (descriptive)\n")
    rows = []
    for arm, v in r["arms"].items():
        f, c = v["fixed"]["fixed_risk"], v["compounding"]
        ci = f["net_r_ci95"] or [float("nan")] * 2
        rows.append([arm, str(v["fixed"]["trades"]),
                     "n/a" if v["fixed"]["win_rate"] is None else f"{v['fixed']['win_rate']:.0%}",
                     "n/a" if f["gross_r_per_trade"] is None else f"{f['gross_r_per_trade']:+.3f}",
                     "n/a" if f["net_r_per_trade"] is None else
                     f"{f['net_r_per_trade']:+.3f} [{ci[0]:+.3f}, {ci[1]:+.3f}]",
                     f"{f['max_drawdown_r']:.1f}", f"£{c['net_gbp']:,.2f}",
                     "n/a" if v["stress_net_r"] is None else f"{v['stress_net_r']:+.3f}",
                     v["stop_usd_quantiles"]])  # fmt: skip
    w.append(_table(["Arm", "Trades", "Win rate", "Gross R/trade", "Net R/trade [95% CI]",
                     "Max DD (R)", "Compounding net", "Net R, 40-pt entry stress",
                     "Stop USD (10/50/90%)"], rows))  # fmt: skip
    w.append("\nRejected signals and reasons:\n")
    w.append(_table(["Arm", "Reasons"], [[a, "; ".join(f"{k}: {n}" for k, n in
                                                        v["rejections"].items()) or "none"]
                                         for a, v in r["arms"].items()]))  # fmt: skip
    w.append("\nBy year and session (fixed risk: trades / mean R / sum R):\n")
    w.append(_table(["Arm", "Year / session", "Trades", "Mean R", "Sum R"],
                    [[a, k, str(n), f"{mean:+.3f}", f"{s:+.2f}"]
                     for a, v in r["arms"].items()
                     for k, (n, mean, s) in v["by_year_and_session"].items()]
                    or [["-"] * 5]))  # fmt: skip
    w.append("\n## Costs and quote evidence\n")
    w.append(f"- Entry-bar spread, points (10/50/90%): {r['entry_bar_spread_points']}")
    w.append(f"- Estimated cost ÷ stop distance (10/50/90%): {r['estimated_cost_over_stop']}; "
             "share within the 0.10R floor: "
             f"{_pct(r['share_within_cost_floor'])}")
    w.append(f"- Quote observations: {r['quote_observations']} (no quote within 60 s: "
             f"{r['no_quote']}). Adverse movement of the executable quote after the entry "
             "moment, points (10/50/90%): " + "; ".join(
                 f"+{k}s {v}" for k, v in r["adverse_quote_points_10_50_90"].items()))  # fmt: skip
    w.append(
        f"- Backtest entry model minus first real quote, points (10/50/90%): "
        f"{r['model_minus_first_quote_points']}. Assumed entry slippage: 7 points (base), "
        "0 and 40 (scenarios). Quote movement is not execution slippage."
    )
    w.append("\n## Data completeness and calendar\n")
    w.append(
        f"- Bars in the window: {r['bars_in_window']}; gaps over 15 minutes in scheduled "
        f"hours: {r['gaps_over_15_min']}."
    )
    w.append(
        f"- Signals logged {r['signals_logged']}, recomputed from stored bars "
        f"{r['signals_recomputed']}, log matches: {r['log_matches_recomputation']}; "
        f"inconsistencies recorded: {r['inconsistencies']}; detection lag seconds "
        f"(10/50/90%): {r['detection_lag_seconds']}."
    )
    w.append(
        f"- Calendar: days without coverage: {r['calendar_days_uncovered'] or 'none'}; "
        f"events in window: {r['calendar_events_in_window'] or 'none'}; published "
        f"coverage ends {r['calendar_published_coverage_to']} (after that only scheduled "
        "dates: rebuild the calendar regularly)."
    )
    return "\n".join(w) + "\n"


if __name__ == "__main__":
    main()
