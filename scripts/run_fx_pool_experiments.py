"""EXP-013: event study and fixed-parameter backtest for Strategy A on EURUSD, GBPUSD and
USDJPY (registered before running: docs/research/experiments/EXP-013-fx-pool-backtest.md).

    uv run python scripts/run_fx_pool_experiments.py --require-clean

Offline backtest. Broker margin comes from MT5 `calc_margin` through a read-only session,
requested for each instrument's own real symbol (the bug this pool's generic engine exists to
avoid: the frozen engine always asked for "XAUUSD"). Nothing is sent to the market.
"""

import argparse
import dataclasses
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from trading.backtest.engine import BacktestResult, ExecutionCosts, Outcome, TradeRecord
from trading.backtest.provenance import build_manifest, code_state, file_sha256, unique_paths
from trading.backtest.runner import PERIODS
from trading.market_data.mcp_collector import MarginSession
from trading.models import Direction
from trading.research.candidate_engine import CandidateOptions
from trading.research.fx_pool_forward import SPECS, FxPoolInputs
from trading.research.levels import ny_time, trading_day
from trading.research.multi_market import GenericCandidateBacktest, GenericStrategyA
from trading.research.news import NewsFilter, load_calendar
from trading.research.stats import bootstrap_mean, r_net, summarise

CALENDAR = Path("config/economic_calendar.yaml")
SPEC_DOC = Path("docs/research/strategy-a-fx-pool.md")
PROGRAMME = Path("docs/research/xauusd-research-programme.md")
REPORTS = Path("reports/research")
KINDS = ["fomc_statement", "cpi", "employment_situation"]
CONVERSIONS = {"EURUSD": "GBPUSD", "GBPUSD": "GBPUSD", "USDJPY": "GBPJPY"}
STUDY_FROM, STUDY_TO = datetime(2023, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC)
ARMS = {"no cost floor": None, "0.10R cost floor": Decimal("0.10")}
LABEL = {"Training": "Training 2023-24", "Validation": "Validation 2025",
         "Out of sample": "2026 (development)"}  # fmt: skip


def _table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    return "\n".join(out + ["| " + " | ".join(r) + " |" for r in rows])


def _reason(text: str) -> str:
    """Group reasons that differ only in amounts (e.g. the minimum-volume loss in GBP)."""
    return re.sub(r"\d+(?:\.\d+)?", "N", text)


def event_study(cand: GenericStrategyA, point: Decimal) -> dict[str, Any]:
    """Copied from scripts/run_candidate_experiments.py (EXP-002/004/006), unchanged, rather
    than importing across scripts (scripts/ is not a package)."""
    m = cand.m15
    events = [e for e in cand.events
              if STUDY_FROM <= m[e.anchor].open_time < STUDY_TO]  # fmt: skip
    stages = Counter(e.stage for e in events)
    by_month = Counter(m[e.anchor].open_time.strftime("%Y-%m") for e in events)
    by_hour = Counter(ny_time(m[e.anchor].open_time).hour for e in events)
    signals = [e for e in events if e.stage == "signal" and e.signal_index is not None]
    rows = []
    for e in signals:
        j = e.signal_index
        assert j is not None
        sig = cand.signals.get(j)
        if sig is None or j + 1 >= len(m):
            continue
        setup, fill = sig.setup, m[j + 1]
        buy = setup.direction == Direction.BUY
        bid = Decimal(str(fill.open))
        entry = bid + fill.spread_points * point if buy else bid
        risk = abs(entry - setup.stop)
        if risk == 0:
            continue
        cost = (fill.spread_points + 7 + 40) * point
        window = m[j + 1 : j + 17]
        if buy:
            mfe = max(Decimal(str(b.high)) for b in window) - entry
            mae = entry - min(Decimal(str(b.low)) for b in window)
        else:
            mfe = entry - min(Decimal(str(b.low)) + b.spread_points * point for b in window)
            mae = max(Decimal(str(b.high)) + b.spread_points * point for b in window) - entry
        first = "neither"
        for b in window:  # which comes first within 16 bars, before costs: +2R or -1R
            hi = Decimal(str(b.high)) + (0 if buy else b.spread_points * point)
            lo = Decimal(str(b.low)) + (0 if buy else b.spread_points * point)
            adverse = (lo <= entry - risk) if buy else (hi >= entry + risk)
            favourable = (hi >= entry + 2 * risk) if buy else (lo <= entry - 2 * risk)
            if adverse:
                first = "-1R first (or same bar)"
                break
            if favourable:
                first = "+2R first"
                break
        rows.append({"atr15": setup.atr, "stop_usd": float(risk),
                     "stop_atr": float(risk) / setup.atr if setup.atr else None,
                     "cost_r": float(cost / risk), "mfe_r": float(mfe / risk),
                     "mae_r": float(mae / risk), "first": first})  # fmt: skip

    def q(key: str) -> list[float]:
        values = sorted(r[key] for r in rows if r[key] is not None)
        if not values:
            return []
        return [values[int(p * (len(values) - 1))] for p in (0.1, 0.25, 0.5, 0.75, 0.9)]

    return {
        "period": "2023-01-01 to 2025-01-01",
        "events": len(events), "stages": dict(stages.most_common()),
        "signals": len(rows),
        "events_by_month": dict(sorted(by_month.items())),
        "events_by_new_york_hour": dict(sorted(by_hour.items())),
        "quantiles_10_25_50_75_90": {k: q(k) for k in ("atr15", "stop_usd", "stop_atr", "cost_r",
                                                       "mfe_r", "mae_r")},
        "share_within_cost_floor": (sum(r["cost_r"] <= 0.10 for r in rows) / len(rows))
        if rows else None,
        "first_touch_16_bars_before_costs": dict(Counter(r["first"] for r in rows)),
    }  # fmt: skip


def period_summary(result: BacktestResult) -> dict[str, Any]:
    events = {(s.direction, s.pullback_event) for s in result.signals}
    s = summarise(result.trades, result.starting_balance, events=len(events))
    s["signals"] = len(result.signals)
    s["rejections"] = dict(Counter(_reason(sig.reasons[0]) for sig in result.signals
                                   if sig.outcome != Outcome.EXECUTABLE).most_common())  # fmt: skip
    s["outcomes"] = dict(Counter(sig.outcome.value for sig in result.signals))
    return s


def classify(arm: dict[str, Any], base: str, stress: str, zero_labels: list[str],
             pooled_trades: list[TradeRecord],
             ratio: dict[Any, float | None]) -> dict[str, Any]:  # fmt: skip
    """Pre-registered decision rule (registry EXP-013 and programme Amendment 3), copied
    unchanged from scripts/run_candidate_experiments.py for the same reason as event_study."""
    primary = arm["news on"]["fixed"][base]
    periods = [p for p, _, _ in PERIODS]
    rs = [r_net(t) for t in pooled_trades]
    mean, lo, hi = bootstrap_mean(rs)
    top = sorted(rs, reverse=True)
    stress_trades = arm["_trades"]["fixed"][stress]
    stress_mean = statistics.fmean(r_net(t) for t in stress_trades) if stress_trades else None
    zero_positive = any(
        statistics.fmean(r_net(t) for t in arm["_trades"]["fixed"][z]) > 0
        for z in zero_labels if arm["_trades"]["fixed"][z])  # fmt: skip
    train = sorted(x for t in pooled_trades
                   if t.entry_time < datetime(2025, 1, 1, tzinfo=UTC)
                   and (x := ratio.get(trading_day(t.entry_time))) is not None)  # fmt: skip
    terciles: dict[str, list[float]] = defaultdict(list)
    if len(train) >= 3:
        a, b = train[len(train) // 3], train[2 * len(train) // 3]
        for t in pooled_trades:
            x = ratio.get(trading_day(t.entry_time))
            if x is not None:
                terciles["low" if x < a else "normal" if x < b else "high"].append(r_net(t))
    tercile_means = {k: statistics.fmean(v) for k, v in terciles.items() if v}
    events = {p: primary[p]["events"] for p in periods}
    gross_pos = all((primary[p]["fixed_risk"]["gross_r_per_trade"] or 0) > 0 for p in periods)
    net_pos = all((primary[p]["fixed_risk"]["net_r_per_trade"] or 0) > 0 for p in periods)
    checks = {
        "events_per_period": events,
        "gross_and_net_positive_every_period": gross_pos and net_pos,
        "pooled_net_r": [mean, lo, hi],
        "pooled_ci_above_zero": lo > 0 if rs else False,
        "sum_r_without_best_10": sum(top[10:]),
        "stress_40pt_entry_net_r": stress_mean,
        "volatility_tercile_net_r": tercile_means,
        "positive_in_two_of_three_terciles": sum(v > 0 for v in tercile_means.values()) >= 2,
    }
    insufficient = [p for p, n in events.items() if n < 100]
    candidate = (gross_pos and net_pos and checks["pooled_ci_above_zero"]
                 and checks["sum_r_without_best_10"] > 0 and (stress_mean or 0) > 0
                 and checks["positive_in_two_of_three_terciles"])  # fmt: skip
    if candidate:
        label = "CANDIDATE FOR THE FORWARD HOLD-OUT ONLY (not 'profitable')"
    elif rs and hi < 0:
        label = "NEGATIVE"
    elif zero_positive and mean <= 0:
        label = "ASSUMPTION-DEPENDENT (positive only with zero entry slippage)"
    else:
        label = "INCONCLUSIVE"
    if insufficient:
        label += f"; INSUFFICIENT DATA in {', '.join(LABEL[p] for p in insufficient)}"
    checks["classification"] = label
    return checks


def run_one(
    inp: FxPoolInputs,
    symbol: str,
    cand: GenericStrategyA,
    costs: ExecutionCosts,
    options: CandidateOptions,
    provider: Any,
) -> dict[str, BacktestResult]:
    conversion_symbol = CONVERSIONS[symbol]
    out = {}
    for name, start, end in PERIODS:
        config = dataclasses.replace(inp.base_config, costs=costs, trade_from=start,
                                     trade_until=end)  # fmt: skip
        engine = GenericCandidateBacktest(
            candidate=cand, options=options, symbol=symbol, conversion_symbol=conversion_symbol,
            m15=inp.m15(symbol), h1=inp.h1(symbol), conversion_m15=inp.m15(conversion_symbol),
            spec=SPECS[symbol], conversion_spec=SPECS[conversion_symbol], calendar=inp.calendar,
            config=config, margin_provider=provider)  # fmt: skip
        out[name] = engine.run()
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
    inp = FxPoolInputs()
    news = NewsFilter(load_calendar(CALENDAR), KINDS)
    grid = inp.cost_model.grid()
    base = inp.cost_model.base()
    stress = next(c for c in grid if c.entry_points == 40
                  and c.stop_exit_points == base.stop_exit_points)  # fmt: skip
    zero = [c.label for c in grid if c.entry_points == 0]

    studies: dict[str, Any] = {}
    results: dict[str, Any] = {}
    with MarginSession() as session:

        def provider_for(symbol: str) -> Any:
            def provider(side: str, volume: Decimal, price: Decimal) -> dict[str, Any]:
                return session.margin(symbol=symbol, side=side, volume=float(volume),
                                      price=float(price))  # type: ignore[arg-type]  # fmt: skip

            return provider

        for symbol in ("EURUSD", "GBPUSD", "USDJPY"):
            point = Decimal(str(SPECS[symbol].point))
            cand = GenericStrategyA(inp.m15(symbol), inp.h1(symbol), inp.calendar, point, symbol)
            studies[symbol] = event_study(cand, point)
            provider = provider_for(symbol)
            ratio = {d.day: cand.levels.adr_ratio(d.day) for d in cand.levels.days}
            per_arm: dict[str, Any] = {}
            for arm, floor in ARMS.items():
                arm_out: dict[str, Any] = {"news on": {"fixed": {}, "compounding": {}},
                                           "news off": {"fixed": {}, "compounding": {}},
                                           "_trades": {"fixed": {}}}  # fmt: skip
                for news_label, news_filter, scenarios in (("news on", news, grid),
                                                           ("news off", None, [base])):  # fmt: skip
                    for ledger in ("fixed", "compounding"):
                        for costs in scenarios:
                            opts = CandidateOptions(cost_floor=floor, news=news_filter,
                                                    fixed_risk=ledger == "fixed")  # fmt: skip
                            by_period = run_one(inp, symbol, cand, costs, opts, provider)
                            arm_out[news_label][ledger][costs.label] = {
                                p: period_summary(r) for p, r in by_period.items()}  # fmt: skip
                            if news_label == "news on" and ledger == "fixed":
                                arm_out["_trades"]["fixed"][costs.label] = [
                                    t for r in by_period.values() for t in r.trades]  # fmt: skip
                pooled = arm_out["_trades"]["fixed"][base.label]
                arm_out["decision"] = classify(arm_out, base.label, stress.label, zero, pooled,
                                               ratio)  # fmt: skip
                arm_out.pop("_trades")
                per_arm[arm] = arm_out
            results[symbol] = per_arm

    stamp = f"{code['short_commit']}{'-dirty' if code['dirty'] else ''}"
    study_report, study_manifest = unique_paths(args.reports_dir, f"EXP-013-events_{stamp}")
    report_path, manifest_path = unique_paths(args.reports_dir, f"EXP-013_{stamp}")
    paths = {"fx_pool_history": Path("data/history/fx_pool.local.json"),
            "xauusd_history_for_gbpusd": Path("data/history/xauusd_backtest.local.json"),
            "economic_calendar": CALENDAR, "specification": SPEC_DOC,
            "programme": PROGRAMME}  # fmt: skip
    params = {"strategy": "A: session breakout and retest (FX pool)",
             "specification_sha256": file_sha256(SPEC_DOC), "base_scenario": base.label,
             "stress_scenario": stress.label, "news_filter": "FOMC, CPI, Employment Situation",
             "cost_status": {"spread": "measured per instrument",
                             "stop_and_entry_slippage": "carried over from gold's evidence, "
                             "not measured for EURUSD/GBPUSD/USDJPY (see specification "
                             "section 3)"}}  # fmt: skip
    m1 = build_manifest(code=code, started=started, command=sys.argv, input_paths=paths,
                        parameters={**params, "experiment": "EXP-013-events"},
                        manifest_path=study_manifest, results=studies)  # fmt: skip
    study_manifest.write_text(json.dumps(m1, indent=2, sort_keys=True), encoding="utf-8")
    study_report.write_text(render_study(m1), encoding="utf-8")
    m2 = build_manifest(code=code, started=started, command=sys.argv, input_paths=paths,
                        parameters={**params, "experiment": "EXP-013"},
                        manifest_path=manifest_path, results=results)  # fmt: skip
    manifest_path.write_text(json.dumps(m2, indent=2, sort_keys=True), encoding="utf-8")
    report_path.write_text(render_backtest(m2, base.label, grid), encoding="utf-8")
    print(f"{study_report}\n{report_path}")


def render_study(m: dict[str, Any]) -> str:
    r = m["results"]
    w = [f"<!-- run {m['run_id']} -->", "# EXP-013: FX pool setup event study (2023-2024)", "",
         "Descriptive only. Registered before running.", "",
         f"- Code `{m['code']['commit']}`; working tree "
         f"{'DIRTY' if m['code']['dirty'] else 'clean'}", ""]  # fmt: skip
    for symbol, s in r.items():
        w.append(f"## {symbol}\n")
        w.append(f"- Setup events detected: **{s['events']}**; reaching a signal: "
                 f"**{s['signals']}**.\n")  # fmt: skip
        w.append(_table(["Final stage", "Events"], [[k, str(v)] for k, v in s["stages"].items()]))
        share = s["share_within_cost_floor"]
        w.append(f"\nShare of signals within the 0.10R cost floor: "
                 f"{'n/a' if share is None else f'{share:.0%}'}\n")  # fmt: skip
    return "\n".join(w) + "\n"


def render_backtest(m: dict[str, Any], base: str, grid: list[ExecutionCosts]) -> str:
    r = m["results"]
    w = [f"<!-- run {m['run_id']} -->", "# EXP-013: FX pool fixed-parameter backtest", "",
         "Research only. Registered before running. No orders; MT5 used read-only for "
         "margin (requested for each instrument's own real symbol). Parameters fixed; "
         "nothing tuned.", "",
         "**Costs:** spread measured per instrument; entry and stop-exit slippage are "
         "carried over from gold's own evidence, not measured for these instruments "
         "(specification section 3) — stated plainly because it may not be the right scale "
         "for a pair with a much tighter typical stop than gold.", ""]  # fmt: skip
    for symbol, arms in r.items():
        w.append(f"## {symbol}\n")
        for arm, out in arms.items():
            d = out["decision"]
            w.append(f"### Arm: {arm}\n")
            w.append(f"**Pre-registered classification: {d['classification']}**\n")
            rows = []
            for period, _, _ in PERIODS:
                f_s = out["news on"]["fixed"][base][period]
                f = f_s["fixed_risk"]
                ci = f["net_r_ci95"] or [float("nan")] * 2
                rows.append([LABEL[period], str(f_s["signals"]), str(f_s["events"]),
                            str(f_s["trades"]),
                            "n/a" if f_s["win_rate"] is None else f"{f_s['win_rate']:.1%}",
                            "n/a" if f["gross_r_per_trade"] is None
                            else f"{f['gross_r_per_trade']:+.3f}",
                            "n/a" if f["net_r_per_trade"] is None else
                            f"{f['net_r_per_trade']:+.3f} "
                            f"[{ci[0]:+.3f}, {ci[1]:+.3f}]"])  # fmt: skip
            w.append(_table(["Period", "Signals", "Events", "Trades", "Win rate",
                             "Gross R/trade", "Net R/trade [95% CI]"], rows))  # fmt: skip
            w.append("")
    return "\n".join(w) + "\n"


if __name__ == "__main__":
    main()
