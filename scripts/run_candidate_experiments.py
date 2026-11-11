"""Event study and fixed-parameter backtest for one candidate strategy (registered before
running: docs/research/experiments/EXP-002..EXP-007).

    uv run python scripts/run_candidate_experiments.py --strategy A --require-clean

Offline backtest. Broker margin comes from MT5 `calc_margin` through a read-only session, as
in Version 1.0; nothing is sent to the market. Each run writes new reports; none is replaced.
"""

import argparse
import dataclasses
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from trading.backtest.engine import BacktestResult, ExecutionCosts, Outcome, TradeRecord
from trading.backtest.provenance import build_manifest, code_state, file_sha256, unique_paths
from trading.backtest.runner import PERIODS
from trading.market_data.mcp_collector import MarginSession
from trading.models import Direction
from trading.research.candidate_engine import CandidateBacktest, CandidateOptions, with_period
from trading.research.candidates import STRATEGIES, Candidate
from trading.research.inputs import load_inputs
from trading.research.levels import ny_time, trading_day
from trading.research.news import NewsFilter, load_calendar
from trading.research.stats import bootstrap_mean, fmt, r_net, summarise

EXPERIMENTS = {"A": ("EXP-002", "EXP-003"), "C": ("EXP-004", "EXP-005"),
               "B": ("EXP-006", "EXP-007")}  # fmt: skip
CANDIDATES = Path("docs/research/xauusd-strategy-candidates.md")
PROGRAMME = Path("docs/research/xauusd-research-programme.md")
CALENDAR = Path("config/economic_calendar.yaml")
REPORTS = Path("reports/research")
STUDY_FROM, STUDY_TO = datetime(2023, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC)
ARMS = {"no cost floor": None, "0.10R cost floor": Decimal("0.10")}
LABEL = {"Training": "Training 2023-24", "Validation": "Validation 2025",
         "Out of sample": "2026 (development)"}  # fmt: skip
M15 = timedelta(minutes=15)


def _table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    return "\n".join(out + ["| " + " | ".join(r) + " |" for r in rows])


# --- event study (2023-2024, descriptive) ---------------------------------------------------


def event_study(cand: Candidate, point: Decimal) -> dict[str, Any]:
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


# --- backtest -------------------------------------------------------------------------------


def run_one(inp: Any, cand: Candidate, costs: ExecutionCosts, options: CandidateOptions,
            provider: Any) -> dict[str, BacktestResult]:  # fmt: skip
    out = {}
    for name, start, end in PERIODS:
        config = with_period(dataclasses.replace(inp.base_config, costs=costs), start, end)
        engine = CandidateBacktest(candidate=cand, options=options, m15=inp.m15, h1=inp.h1,
                                   conversion_m15=inp.gbpusd_m15, spec=inp.spec,
                                   conversion_spec=inp.conversion_spec, calendar=inp.calendar,
                                   config=config, margin_provider=provider)  # fmt: skip
        out[name] = engine.run()
    return out


def _reason(text: str) -> str:
    """Group reasons that differ only in amounts (e.g. the minimum-volume loss in GBP)."""
    return re.sub(r"\d+(?:\.\d+)?", "N", text)


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
    """Pre-registered decision rule (registry EXP-003/5/7 and programme Amendment 3)."""
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
    # Volatility terciles: cut-offs from 2023-24 trades of this arm.
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


def main() -> None:  # noqa: PLR0915
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", choices=sorted(STRATEGIES), required=True)
    parser.add_argument("--require-clean", action="store_true")
    parser.add_argument("--reports-dir", type=Path, default=REPORTS)
    args = parser.parse_args()
    started = datetime.now(UTC)
    code = code_state()
    if args.require_clean and code["dirty"]:
        raise SystemExit(f"uncommitted changes: {code['uncommitted_files']}")
    study_id, backtest_id = EXPERIMENTS[args.strategy]
    inp = load_inputs()
    tick = Decimal(str(inp.spec.tick_size))
    point = Decimal(str(inp.spec.point or inp.spec.tick_size))
    cand = STRATEGIES[args.strategy](inp.m15, inp.h1, inp.calendar, tick)
    news = NewsFilter(load_calendar(CALENDAR), ["fomc_statement"])
    study = event_study(cand, point)
    grid = inp.cost_model.grid()
    base = inp.cost_model.base()
    stress = next(c.label for c in grid if c.entry_points == 40
                  and c.stop_exit_points == base.stop_exit_points)  # fmt: skip
    zero = [c.label for c in grid if c.entry_points == 0]
    ratio = {d.day: cand.levels.adr_ratio(d.day) for d in cand.levels.days}

    results: dict[str, Any] = {}
    with MarginSession() as session:

        def provider(side: str, volume: Decimal, price: Decimal) -> dict[str, Any]:
            return session.margin(symbol="XAUUSD", side=side, volume=float(volume),
                                  price=float(price))  # type: ignore[arg-type]  # fmt: skip

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
                        by_period = run_one(inp, cand, costs, opts, provider)
                        arm_out[news_label][ledger][costs.label] = {
                            p: period_summary(r) for p, r in by_period.items()}  # fmt: skip
                        if news_label == "news on" and ledger == "fixed":
                            arm_out["_trades"]["fixed"][costs.label] = [
                                t for r in by_period.values() for t in r.trades]  # fmt: skip
            pooled = arm_out["_trades"]["fixed"][base.label]
            arm_out["decision"] = classify(arm_out, base.label, stress, zero, pooled, ratio)
            arm_out.pop("_trades")
            results[arm] = arm_out

    stamp = f"{code['short_commit']}{'-dirty' if code['dirty'] else ''}"
    study_report, study_manifest = unique_paths(args.reports_dir, f"{study_id}_{stamp}")
    report_path, manifest_path = unique_paths(args.reports_dir, f"{backtest_id}_{stamp}")
    common_inputs = {**inp.paths, "economic_calendar": CALENDAR, "candidates": CANDIDATES,
                     "programme": PROGRAMME}  # fmt: skip
    params = {
        "strategy": cand.name, "specification": str(CANDIDATES),
        "specification_sha256": file_sha256(CANDIDATES),
        "programme_sha256": file_sha256(PROGRAMME),
        "engine_params": dataclasses.asdict(cand.params),
        "arms": {k: str(v) for k, v in ARMS.items()},
        "news_filter": "FOMC statements only (Amendment 2): CPI and Employment Situation not "
                       "filtered (bls.gov refused automated access)",
        "cost_scenarios": [c.label for c in grid], "base_scenario": base.label,
        "stress_scenario": stress,
        "cost_status": {"spread": "measured (bar spread)", "stop_slippage": "measured percentiles",
                        "entry_and_market_exit_slippage": "assumed scenarios",
                        "commission": "measured £0", "take_profit": "measured 0",
                        "swap": "0 (no overnight positions)"},
        "margin": "MT5 calc_margin, read-only (today's leverage)",
    }  # fmt: skip
    m1 = build_manifest(code=code, started=started, command=sys.argv, input_paths=common_inputs,
                        parameters={**params, "experiment": study_id},
                        manifest_path=study_manifest, results=study)  # fmt: skip
    study_manifest.write_text(json.dumps(m1, indent=2, sort_keys=True), encoding="utf-8")
    study_report.write_text(render_study(m1, study_id, cand.name), encoding="utf-8")
    m2 = build_manifest(code=code, started=started, command=sys.argv, input_paths=common_inputs,
                        parameters={**params, "experiment": backtest_id},
                        manifest_path=manifest_path, results=results)  # fmt: skip
    manifest_path.write_text(json.dumps(m2, indent=2, sort_keys=True), encoding="utf-8")
    report_path.write_text(render_backtest(m2, backtest_id, cand.name, base.label, grid),
                           encoding="utf-8")  # fmt: skip
    print(f"{study_report}\n{report_path}")


# --- reports --------------------------------------------------------------------------------


def _provenance(m: dict[str, Any]) -> list[str]:
    c = m["code"]
    w = [f"- Run `{m['run_id']}`; command `{m['command']}`",
         f"- Code `{c['commit']}` on `{c['branch']}`; working tree "
         f"{'DIRTY: ' + ', '.join(c['uncommitted_files']) if c['dirty'] else 'clean'}"]  # fmt: skip
    for name, info in m["inputs"].items():
        w.append(f"- Input `{name}`: `{info['path']}` sha256 `{info['sha256'][:16]}…`")
    return w


def render_study(m: dict[str, Any], exp: str, name: str) -> str:
    r = m["results"]
    w = [f"<!-- run {m['run_id']} -->", f"# {exp}: strategy {name}, setup event study (2023–2024)",
         "", "Descriptive only. Registered before running. No parameter or arm is chosen from "
         "it.", "", *_provenance(m), ""]  # fmt: skip
    w += [f"- Setup events detected: **{r['events']}**; reaching a signal: **{r['signals']}** "
          "(one signal per event).", ""]  # fmt: skip
    w.append(_table(["Final stage", "Events"], [[k, str(v)] for k, v in r["stages"].items()]))
    w.append("\nQuantiles at the signal (10th / 25th / 50th / 75th / 90th):\n")
    labels = {"atr15": "ATR15 (USD)", "stop_usd": "Stop distance (USD)",
              "stop_atr": "Stop distance (ATR15)", "cost_r": "Estimated cost C (R)",
              "mfe_r": "Max favourable excursion, 16 bars (R)",
              "mae_r": "Max adverse excursion, 16 bars (R)"}  # fmt: skip
    rows = [[labels[k], " / ".join(f"{x:.2f}" for x in v)]
            for k, v in r["quantiles_10_25_50_75_90"].items()]  # fmt: skip
    w.append(_table(["Measure", "Quantiles"], rows))
    share = r["share_within_cost_floor"]
    w.append(f"\nShare of signals within the 0.10R cost floor: "
             f"{'n/a' if share is None else f'{share:.0%}'}.\n")  # fmt: skip
    w.append("First touch within 16 bars, before costs (executable prices): " + "; ".join(
        f"{k}: {v}" for k, v in r["first_touch_16_bars_before_costs"].items()) + "\n")  # fmt: skip
    w.append(_table(["New York hour of the event", "Events"],
                    [[f"{int(h):02d}:00", str(n)]
                     for h, n in r["events_by_new_york_hour"].items()]))  # fmt: skip
    w.append("\n" + _table(["Month", "Events"],
                           [[k, str(v)] for k, v in r["events_by_month"].items()]))  # fmt: skip
    w.append(
        "\nLimitations: viewed history; one spread value per bar; excursions use M15 "
        "extremes; not news-filtered (describes all setups)."
    )
    return "\n".join(w) + "\n"


def render_backtest(m: dict[str, Any], exp: str, name: str, base: str,
                    grid: list[ExecutionCosts]) -> str:  # noqa: PLR0915  # fmt: skip
    res = m["results"]
    w = [f"<!-- run {m['run_id']} -->", f"# {exp}: strategy {name}, fixed-parameter backtest", "",
         "Research only. Registered before running. No orders; MT5 used read-only for margin. "
         "Parameters fixed; nothing tuned. **2026 is development evidence; 2026-11-01 onwards "
         "is excluded (the forward hold-out starts 2026-11-16).**", "", *_provenance(m), "",
         "**News filter: partial — FOMC statements only; CPI and payrolls are not filtered** "
         "(bls.gov refused automated access; programme Amendment 2).", "",
         "**Costs:** spread and stop slippage measured; entry and market-exit slippage are "
         "assumed scenarios; commission £0 and take-profit slippage 0 measured; swap 0 (no "
         "overnight positions). Fixed risk = 2% of a constant £1,000 (R; £20 per R); "
         "compounding = 2% of a running £1,000 per period.", ""]  # fmt: skip
    for arm, out in res.items():
        d = out["decision"]
        w.append(f"## Arm: {arm}\n")
        w.append(f"**Pre-registered classification: {d['classification']}**\n")
        lo_hi = d["pooled_net_r"]
        w.append(f"- Pooled net R/trade {lo_hi[0]:+.3f} [95% CI {lo_hi[1]:+.3f}, {lo_hi[2]:+.3f}];"
                 f" sum R without the best 10 trades {d['sum_r_without_best_10']:+.1f}; "
                 f"40-point entry stress {fmt(d['stress_40pt_entry_net_r'])}; volatility "
                 f"terciles " + ", ".join(f"{k} {v:+.3f}" for k, v in
                                          d["volatility_tercile_net_r"].items()))  # fmt: skip
        w.append("- Events with a signal per period: " + ", ".join(
            f"{LABEL[p]} {n}" for p, n in d["events_per_period"].items()) + "\n")  # fmt: skip
        rows = []
        for period, _, _ in PERIODS:
            f_s = out["news on"]["fixed"][base][period]
            c_s = out["news on"]["compounding"][base][period]
            f, g = f_s["fixed_risk"], c_s["compounding"]
            ci = f["net_r_ci95"] or [float("nan")] * 2
            rows.append([LABEL[period], str(f_s["signals"]), str(f_s["events"]),
                         str(f_s["trades"]),
                         "n/a" if f_s["win_rate"] is None else f"{f_s['win_rate']:.1%}",
                         fmt(f["average_win_r"], 2), fmt(f["average_loss_r"], 2),
                         fmt(f["gross_r_per_trade"]),
                         f"{fmt(f['net_r_per_trade'])} [{ci[0]:+.3f}, {ci[1]:+.3f}]",
                         fmt(f["profit_factor"], 2, False), fmt(f["max_drawdown_r"], 1, False),
                         f"£{f['net_gbp']:,.2f}", f"£{g['net_gbp']:,.2f}",
                         f"{g['max_drawdown_percent']:.1f}%",
                         fmt(f_s["cost_r_per_trade"])])  # fmt: skip
        w.append(_table(["Period", "Signals", "Events", "Trades", "Win rate", "Avg win R",
                         "Avg loss R", "Gross R/trade", "Net R/trade [95% CI]", "PF (R)",
                         "Max DD (R)", "Fixed-risk net", "Compounding net",
                         "Compounding max DD", "Cost R/trade"], rows))  # fmt: skip
        w.append("\nRejections and reasons (base scenario, fixed risk, news on):\n")
        rows = []
        for period, _, _ in PERIODS:
            rej = out["news on"]["fixed"][base][period]["rejections"]
            rows.append([LABEL[period], "; ".join(f"{k}: {v}" for k, v in rej.items()) or "none"])
        w.append(_table(["Period", "Rejected or filtered signals"], rows))
        w.append("\nCosts (base, fixed risk, news on, GBP at 2% of £1,000):\n")
        rows = []
        for period, _, _ in PERIODS:
            c = out["news on"]["fixed"][base][period]["costs_gbp"]
            rows.append([LABEL[period], *(f"£{c[k]:,.2f}" for k in (
                "spread", "entry_slippage", "exit_slippage", "commission", "swap"))])  # fmt: skip
        w.append(_table(["Period", "Spread (measured)", "Entry slippage (assumed)",
                         "Exit slippage (stop: measured pct; market: assumed)", "Commission",
                         "Swap"], rows))  # fmt: skip
        w.append(
            "\nCost scenarios (fixed risk, news on): net R per trade, Training / Validation "
            "/ 2026; trades in brackets:\n"
        )
        rows = []
        for costs in grid:
            runs = out["news on"]["fixed"][costs.label]
            cells = [f"{fmt(runs[p]['fixed_risk']['net_r_per_trade'])} ({runs[p]['trades']})"
                     for p, _, _ in PERIODS]  # fmt: skip
            rows.append([costs.label + (" **(base)**" if costs.label == base else ""),
                         " / ".join(cells)])  # fmt: skip
        w.append(_table(["Scenario", "Net R/trade (trades)"], rows))
        w.append("\nNews calendar impact (base scenario, fixed risk):\n")
        rows = []
        for period, _, _ in PERIODS:
            on = out["news on"]["fixed"][base][period]
            off = out["news off"]["fixed"][base][period]
            excluded = sum(v for k, v in on["rejections"].items()
                           if k.startswith(("news", "economic")))  # fmt: skip
            rows.append([LABEL[period], str(excluded), str(off["trades"]), str(on["trades"]),
                         fmt(off["fixed_risk"]["net_r_per_trade"]),
                         fmt(on["fixed_risk"]["net_r_per_trade"])])  # fmt: skip
        w.append(_table(["Period", "Signals excluded by calendar", "Trades news off",
                         "Trades news on", "Net R/trade news off", "Net R/trade news on"],
                        rows))  # fmt: skip
        w.append("")
    w.append("## Limitations\n")
    w += ["- Viewed history: 2023–2025 viewed, 2026 is development evidence. Nothing here is "
          "out-of-sample; the forward hold-out (from 2026-11-16) has not happened yet.",
          "- One spread value per M15 bar; stop first when a bar touches stop and target; gaps "
          "fill at the open.",
          "- Entry slippage is unknown (scenarios). Margin uses today's leverage.",
          "- News filter is partial (FOMC only).",
          "- Bootstrap intervals treat trades as independent."]  # fmt: skip
    return "\n".join(w) + "\n"


if __name__ == "__main__":
    main()
