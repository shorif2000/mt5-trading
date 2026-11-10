"""Diagnostic review of the XAUUSD Version 1.0 and 1.1 backtests (research only, read-only).

Reads the committed run manifests and the local history file they were run on (checked by
sha256), recomputes entry-time features with the strategy's own indicator code, and writes a
Markdown report. Nothing here changes strategy rules or parameters, and no MT5 access is made.

    uv run python scripts/xauusd_diagnostics.py

Every feature uses only bars completed at the signal close (= the entry bar open). Bucket
thresholds (terciles) are taken from Version 1.0 Training trades and applied unchanged to the
later periods, so the later periods do not set their own cut-offs.
"""

import hashlib
import json
import random
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from trading.analysis.indicators import atr_series
from trading.backtest.history_bars import load_history
from trading.backtest.real_yield import RealYieldFilter, load_series
from trading.models import Direction
from trading.strategies.xauusd_m15_pullback import XauusdM15Pullback

RUNS = {
    "1.0": Path("reports/backtests/20261110T222100Z_7f525aace4.json"),
    "1.1": Path("reports/backtests/20261110T223948Z_9caf03ac73.json"),
}
OUTPUT = Path("reports/diagnostics/xauusd_v1.0_v1.1_diagnostic.md")
PERIODS = ("Training", "Validation", "Out of sample")
LABEL = {"Training": "Training 2023-24", "Validation": "Validation 2025",
         "Out of sample": "2026 (development)"}  # fmt: skip
NY = ZoneInfo("America/New_York")
M15 = timedelta(minutes=15)
SEED = 20261110


@dataclass
class Trade:
    version: str
    period: str
    direction: str
    entry: datetime
    exit: datetime
    exit_reason: str
    r: float  # net / estimated loss at sizing
    gross_r: float
    net: float
    gross: float
    spread: float
    entry_slip: float
    exit_slip: float
    commission: float
    volume: float
    quoted_entry: float
    stop: float
    target: float
    features: dict


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def base_label(manifest: dict) -> str:
    return next(k for k in manifest["results"] if "**" not in k and k.startswith(
        "entry stop-median-proxy") and "p90 (40" in k)  # fmt: skip


# --- statistics ---------------------------------------------------------------------------


def pf(values: list[float]) -> float | None:
    gains = sum(v for v in values if v > 0)
    losses = -sum(v for v in values if v <= 0)
    return gains / losses if losses > 0 else None


def drawdown(values: list[float]) -> float:
    peak = total = worst = 0.0
    for v in values:
        total += v
        peak = max(peak, total)
        worst = max(worst, peak - total)
    return worst


def streaks(values: list[float]) -> tuple[int, int]:
    best = {True: 0, False: 0}
    run, last = 0, None
    for v in values:
        win = v > 0
        run = run + 1 if win == last else 1
        last = win
        best[win] = max(best[win], run)
    return best[True], best[False]


def mean_ci(values: list[float], draws: int = 2000) -> tuple[float, float, float]:
    """Mean and a 95% bootstrap interval (trades resampled independently, which overstates
    precision if outcomes are serially dependent)."""
    if not values:
        return float("nan"), float("nan"), float("nan")
    rng = random.Random(SEED)
    n = len(values)
    means = sorted(sum(rng.choices(values, k=n)) / n for _ in range(draws))
    return statistics.fmean(values), means[int(0.025 * draws)], means[int(0.975 * draws)]


def fmt(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:,.{digits}f}"


def row_stats(trades: list["Trade"]) -> list[str]:
    rs = [t.r for t in trades]
    n = len(rs)
    if n == 0:
        return ["0", "n/a", "n/a", "n/a", "n/a", "n/a"]
    wins = sum(1 for r in rs if r > 0)
    mean, lo, hi = mean_ci(rs)
    return [str(n), f"{wins / n:.1%}", f"{mean:+.3f} [{lo:+.2f}, {hi:+.2f}]", fmt(sum(rs), 1),
            fmt(pf(rs)), fmt(drawdown(rs), 1)]  # fmt: skip


def table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


# --- features --------------------------------------------------------------------------------


class Features:
    def __init__(self, m15: list, h1: list, tick: Decimal) -> None:
        self.m15, self.h1 = m15, h1
        self.strategy = XauusdM15Pullback(m15, h1, tick)
        self.index = {b.open_time: i for i, b in enumerate(m15)}
        self.h1_atr = atr_series([b.high for b in h1], [b.low for b in h1],
                                 [b.close for b in h1], 14)  # fmt: skip
        self.atr_sorted_window = 960  # previous 960 M15 bars, about 10 trading days

    def at(self, trade: dict) -> dict:
        entry = datetime.fromisoformat(trade["entry_time"])
        i = self.index[entry - M15]  # signal bar closes at the entry bar open
        s = self.strategy
        setup = s.evaluate(i)
        if setup is None:
            raise ValueError(f"no setup recomputed at {entry}")
        sign = 1 if trade["direction"] == "buy" else -1
        atr = s.m15_atr[i]
        ema20 = s.m15_ema[i]
        quoted = float(trade["quoted_entry"])
        h = s.last_completed_h1(entry)
        fast, slow, h_atr = s.h1_fast[h], s.h1_slow[h], self.h1_atr[h]
        closes = [b.close for b in self.h1[h - 20 : h + 1]]
        path = sum(abs(b - a) for a, b in zip(closes, closes[1:], strict=False))
        efficiency = abs(closes[-1] - closes[0]) / path if path else 0.0
        history = [a for a in s.m15_atr[max(0, i - self.atr_sorted_window) : i] if a]
        age = 0
        while h - age - 1 >= 0 and s.h1_fast[h - age - 1] and s.h1_slow[h - age - 1] and (
            (s.h1_fast[h - age - 1] - s.h1_slow[h - age - 1]) * sign > 0
        ):
            age += 1
        return {
            "atr": atr,
            "ema20_distance_atr": sign * (quoted - ema20) / atr,
            "stop_atr": abs(quoted - float(trade["stop"])) / atr,
            "stop_usd": abs(quoted - float(trade["stop"])),
            "trend_strength": sign * (fast - slow) / h_atr,
            "efficiency": efficiency,
            "atr_ratio": atr / statistics.median(history) if history else float("nan"),
            "h1_ema50_distance_atr": sign * (quoted - fast) / h_atr,
            "trend_age_h1": age,
            "pullback_event": (trade["direction"], setup.pullback_event_start),
        }


# --- report -----------------------------------------------------------------------------------


def main() -> None:
    manifests = {v: json.loads(p.read_text()) for v, p in RUNS.items()}
    history_path = Path(manifests["1.0"]["inputs"]["history"]["path"])
    for v, m in manifests.items():
        if sha256(history_path) != m["inputs"]["history"]["sha256"]:
            raise SystemExit(f"history file differs from the one run {v} used")
    real_yield_input = manifests["1.1"]["inputs"]["real_yield"]
    if sha256(Path(real_yield_input["path"])) != real_yield_input["sha256"]:
        raise SystemExit("real-yield file differs from the one run 1.1 used")
    bars = load_history(history_path)
    tick = Decimal(str(manifests["1.0"]["parameters"]["instruments"]["XAUUSD"]["tick_size"]))
    features = Features(bars[("XAUUSD", "M15")], bars[("XAUUSD", "H1")], tick)
    gate = RealYieldFilter(load_series(Path(real_yield_input["path"])))

    trades: dict[tuple[str, str], list[Trade]] = {}
    for v, m in manifests.items():
        for period in PERIODS:
            rows = []
            for t in m["base_scenario_trades"][period]:
                loss = float(t["estimated_loss"])
                rows.append(Trade(
                    v, period, t["direction"], datetime.fromisoformat(t["entry_time"]),
                    datetime.fromisoformat(t["exit_time"]), t["exit_reason"],
                    float(t["net_gbp"]) / loss, float(t["gross_gbp"]) / loss,
                    float(t["net_gbp"]), float(t["gross_gbp"]), float(t["spread_cost_gbp"]),
                    float(t["entry_slippage_gbp"]), float(t["exit_slippage_gbp"]),
                    float(t["commission_gbp"]), float(t["volume"]), float(t["quoted_entry"]),
                    float(t["stop"]), float(t["target"]), features.at(t),
                ))  # fmt: skip
            trades[(v, period)] = rows

    out: list[str] = []
    w = out.append
    w("# XAUUSD Version 1.0 and 1.1: diagnostic review of the backtests\n")
    w("Research and diagnosis only. No strategy rule, parameter or risk setting was changed; no "
      "MT5 access was made (the review reads committed manifests and the local history file).\n")
    w("## Inputs\n")
    for v, p in RUNS.items():
        w(f"- Version {v}: `{p}` (commit `{manifests[v]['code']['commit'][:10]}`), base scenario "
          f"`{base_label(manifests[v])}`.")
    w(f"- History: `{history_path}` sha256 `{sha256(history_path)[:16]}…`, matching both runs.")
    w("- Script: `scripts/xauusd_diagnostics.py` (bootstrap seed "
      f"{SEED}). Sessions use New York time, as the approved reports do.")
    w("- **2026 is development evidence, not out-of-sample**: it was examined during Version 1.1 "
      "design. Labelled “2026 (development)” below.\n")
    w("**Units.** The paper ledger compounds (2% of a falling balance), so GBP totals mostly "
      "reflect the balance path. Comparisons below use **R**: each trade's net result divided by "
      "its estimated loss at sizing (the risk the sizing rules accepted). −1R is a full planned "
      "loss. GBP is shown where the task asks for it.\n")

    # 1. expectancy ---------------------------------------------------------------------------
    w("## 1. Trade expectancy\n")
    rows = []
    recon = []
    for v in RUNS:
        for period in PERIODS:
            ts = trades[(v, period)]
            nets = [t.net for t in ts]
            wins = [x for x in nets if x > 0]
            losses = [x for x in nets if x <= 0]
            rs = [t.r for t in ts]
            r_wins = [r for r in rs if r > 0]
            r_losses = [r for r in rs if r <= 0]
            hold = sorted((t.exit - t.entry).total_seconds() / 60 for t in ts)
            cw, cl = streaks(nets)
            rows.append([
                f"{v}", LABEL[period], str(len(ts)), f"{len(wins) / len(ts):.1%}",
                f"£{statistics.fmean(wins):.2f} / {statistics.fmean(r_wins):+.2f}R",
                f"£{statistics.fmean(losses):.2f} / {statistics.fmean(r_losses):+.2f}R",
                f"{statistics.fmean(r_wins) / -statistics.fmean(r_losses):.2f}",
                f"£{statistics.fmean(nets):+.2f} / {statistics.fmean(rs):+.3f}R",
                f"£{sum(wins):,.0f} / £{-sum(losses):,.0f}", fmt(pf(nets)),
                f"{cw} / {cl}", f"{statistics.median(hold):.0f} / {statistics.fmean(hold):.0f}",
            ])  # fmt: skip
            reported = manifests[v]["results"][base_label(manifests[v])][period]
            checks = {
                "trades": (len(ts), reported["trades"]),
                "net": (round(sum(nets), 2), round(float(reported["net_gbp"]), 2)),
                "PF": (round(pf(nets) or 0, 4), round(reported["profit_factor"] or 0, 4)),
                "win rate": (round(len(wins) / len(ts), 4), round(reported["win_rate"], 4)),
                "max consecutive losses": (cl, reported["max_consecutive_losses"]),
                "mean holding (s)": (round(statistics.fmean(hold) * 60),
                                     round(reported["average_holding"])),
            }  # fmt: skip
            bad = [k for k, (a, b) in checks.items() if a != b]
            recon.append(f"- Version {v}, {LABEL[period]}: "
                         + ("all match the report" if not bad else f"MISMATCH in {bad}"))
    w(table(["Ver", "Period", "Trades", "Win rate", "Avg win", "Avg loss", "Win/loss (R)",
             "Expectancy", "Gross profit / loss", "PF", "Max cons. W / L",
             "Hold median / mean (min)"], rows))  # fmt: skip
    w("\nReconciliation against the committed reports (trades, net, profit factor, win rate, "
      "maximum consecutive losses, mean holding time):\n")
    out.extend(recon)
    w("\nWith a 2R target, break-even needs a win rate of about 1 / (1 + win/loss ratio). The "
      "realised win/loss ratio is well under 2 because of costs, forced closes and trend exits "
      "(section 4), so the break-even win rate is higher than the 33% a clean 2R would need.\n")

    # 2. sessions -----------------------------------------------------------------------------
    w("## 2. Trading sessions\n")
    w("Sessions by entry time in New York time. The approved report definition is used: Asia "
      "19:00-03:00, London 03:00-08:00, New York 08:00-17:00. The New York window is split at "
      "12:00 into the London/New York overlap (08:00-12:00, an analysis convention, not an "
      "approved definition) and the New York afternoon. No entries are allowed 16:00-19:00.\n")

    def session(t: Trade) -> str:
        hour = t.entry.astimezone(NY).hour
        if 8 <= hour < 12:
            return "London/NY overlap 08-12"
        if 12 <= hour < 17:
            return "New York afternoon 12-17"
        if 3 <= hour < 8:
            return "London 03-08"
        return "Asia 19-03"

    headers = ["Ver", "Period", "Session", "Trades", "Win rate", "Mean R [95% CI]", "Sum R",
               "PF (R)", "Max DD (R)"]  # fmt: skip
    rows = []
    for v in RUNS:
        for period in PERIODS:
            groups = defaultdict(list)
            for t in trades[(v, period)]:
                groups[session(t)].append(t)
            for name in ("Asia 19-03", "London 03-08", "London/NY overlap 08-12",
                         "New York afternoon 12-17"):  # fmt: skip
                rows.append([v, LABEL[period], name, *row_stats(groups[name])])
    w(table(headers, rows))
    w("")

    # 3. regimes ------------------------------------------------------------------------------
    w("## 3. Market regimes at entry\n")
    w("Measured at the signal close from completed bars only:\n")
    w("- **Trend strength**: (H1 EMA50 − EMA200) in the trade direction ÷ H1 ATR(14).")
    w("- **Range-bound vs directional**: H1 efficiency ratio over the last 20 completed H1 bars "
      "(net move ÷ path length; low = choppy).")
    w("- **Volatility**: M15 ATR(14) ÷ median M15 ATR over the previous 960 M15 bars (about 10 "
      "trading days).\n")
    w("Tercile cut-offs come from Version 1.0 Training trades only and are applied unchanged to "
      "every other period and to Version 1.1.\n")
    train = trades[("1.0", "Training")]
    regimes = {
        "Trend strength": ("trend_strength", ("weak", "medium", "strong")),
        "H1 efficiency": ("efficiency", ("range-bound", "mixed", "directional")),
        "Volatility": ("atr_ratio", ("low", "normal", "high")),
    }
    cuts = {}
    for name, (key, _labels) in regimes.items():
        values = sorted(t.features[key] for t in train)
        cuts[key] = (values[len(values) // 3], values[2 * len(values) // 3])
        w(f"- {name} cut-offs: {cuts[key][0]:.2f} and {cuts[key][1]:.2f}")
    w("")

    def bucket(t: Trade, key: str, labels: tuple[str, ...]) -> str:
        a, b = cuts[key]
        x = t.features[key]
        return labels[0] if x < a else labels[1] if x < b else labels[2]

    for name, (key, labels) in regimes.items():
        w(f"### {name}\n")
        rows = []
        for v in RUNS:
            for period in PERIODS:
                groups = defaultdict(list)
                for t in trades[(v, period)]:
                    groups[bucket(t, key, labels)].append(t)
                for label in labels:
                    rows.append([v, LABEL[period], label, *row_stats(groups[label])])
        w(table(["Ver", "Period", "Bucket", "Trades", "Win rate", "Mean R [95% CI]", "Sum R",
                 "PF (R)", "Max DD (R)"], rows))  # fmt: skip
        w("")

    # 4. entries and exits --------------------------------------------------------------------
    w("## 4. Entries and exits\n")
    rows = []
    for v in RUNS:
        for period in PERIODS:
            ts = trades[(v, period)]
            f = [t.features for t in ts]

            def med(key: str, f: list = f) -> str:
                return f"{statistics.median(x[key] for x in f):.2f}"

            reasons = Counter(t.exit_reason for t in ts)
            n = len(ts)
            stops = sum(c for r, c in reasons.items() if r.startswith("stop"))
            rows.append([
                v, LABEL[period], med("ema20_distance_atr"),
                f"${statistics.median(x['atr'] for x in f):.2f}",
                f"${statistics.median(x['stop_usd'] for x in f):.2f} / {med('stop_atr')}",
                f"{stops / n:.0%}", f"{reasons['target'] / n:.0%}",
                f"{reasons['forced close 16:45 New York'] / n:.0%}",
                f"{reasons['H1 trend invalidated'] / n:.0%}",
                f"{statistics.fmean(t.r for t in ts if t.exit_reason == 'target'):+.2f}",
                f"{statistics.fmean(t.r for t in ts if t.exit_reason.startswith('stop')):+.2f}",
            ])  # fmt: skip
    w(table(["Ver", "Period", "Entry − EMA20 (ATR, median)", "M15 ATR (median)",
             "Stop distance (median, $ / ATR)", "Stops", "Targets", "Forced close",
             "Trend exit", "Mean R at target", "Mean R at stop"], rows))  # fmt: skip
    w("\nMean R by exit reason (all periods, each version):\n")
    rows = []
    for v in RUNS:
        groups = defaultdict(list)
        for period in PERIODS:
            for t in trades[(v, period)]:
                groups[t.exit_reason].append(t)
        for reason, ts in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            rs = [t.r for t in ts]
            rows.append([v, reason, str(len(ts)), f"{statistics.fmean(rs):+.2f}", fmt(sum(rs), 1)])
    w(table(["Ver", "Exit", "Trades", "Mean R", "Sum R"], rows))
    w("\n### Late entries\n")
    w("Two measures of how far into a move the entry is: distance of the entry from H1 EMA50 "
      "in H1 ATRs, and the age of the H1 EMA50/EMA200 alignment in H1 bars. Buckets are "
      "Version 1.0 Training terciles.\n")
    for key, labels, title in (
        ("h1_ema50_distance_atr", ("near EMA50", "middle", "extended"), "Distance from H1 EMA50"),
        ("trend_age_h1", ("young", "middle", "old"), "H1 trend age"),
        ("ema20_distance_atr", ("close to EMA20", "middle", "far from EMA20"),
         "Entry distance from M15 EMA20"),
    ):  # fmt: skip
        values = sorted(t.features[key] for t in train)
        cuts[key] = (values[len(values) // 3], values[2 * len(values) // 3])
        w(f"**{title}** (cut-offs {cuts[key][0]:.2f}, {cuts[key][1]:.2f})\n")
        rows = []
        for v in RUNS:
            for period in PERIODS:
                groups = defaultdict(list)
                for t in trades[(v, period)]:
                    groups[bucket(t, key, labels)].append(t)
                for label in labels:
                    rows.append([v, LABEL[period], label, *row_stats(groups[label])])
        w(table(["Ver", "Period", "Bucket", "Trades", "Win rate", "Mean R [95% CI]", "Sum R",
                 "PF (R)", "Max DD (R)"], rows))  # fmt: skip
        w("")

    # 5. costs ----------------------------------------------------------------------------------
    w("## 5. Transaction costs\n")
    w("| Cost | Status | Source |\n|---|---|---|")
    w("| Spread | **Measured** (historical bar spread) | one spread value per M15 bar from MT5 "
      "history; intrabar widening is not modelled |")
    w("| Entry and market-exit slippage | **Assumed scenario**: 7 points in the base | MT5 records "
      "no requested price for market orders, so it cannot be measured |")
    w("| Stop-loss slippage | **Measured distribution, applied as an assumption**: p90 = 40 "
      "points on every stop in the base | 6,583 of the account's own stop exits |")
    w("| Take-profit slippage | **Measured**: 0 | 165 take-profit exits, median 0 |")
    w("| Commission | **Measured**: £0 | 18,466 historical XAUUSD deals, all 0 |")
    w("| Swap | **0 by design** | no overnight positions (forced close 16:45 New York); swap-free "
      "account |\n")
    rows = []
    for v in RUNS:
        for period in PERIODS:
            ts = trades[(v, period)]
            gross = sum(t.gross for t in ts)
            spread = sum(t.spread for t in ts)
            es = sum(t.entry_slip for t in ts)
            xs = sum(t.exit_slip for t in ts)
            net = sum(t.net for t in ts)
            cost_r = statistics.fmean((t.gross_r - t.r) for t in ts)
            rows.append([
                v, LABEL[period], f"£{gross:,.2f}", f"£{spread:,.2f}", f"£{es:,.2f}",
                f"£{xs:,.2f}", "£0.00", "£0.00", f"£{net:,.2f}",
                "yes" if abs(gross - spread - es - xs - sum(t.commission for t in ts) - net) < 1e-6
                else "NO",
                f"{statistics.fmean(t.gross_r for t in ts):+.3f}", f"{cost_r:.3f}",
                f"{statistics.fmean(t.r for t in ts):+.3f}", fmt(pf([t.gross for t in ts])),
            ])  # fmt: skip
    w(table(["Ver", "Period", "Gross", "Spread", "Entry slip", "Exit slip", "Commission",
             "Swap", "Net", "Reconciles", "Gross R/trade", "Cost R/trade", "Net R/trade",
             "Gross PF"], rows))  # fmt: skip
    w("\nThe cost-scenario grid in each report shows the sensitivity: the optimistic scenario "
      "(zero entry slippage, p50 stops) is still negative in Training for both versions.\n")
    w("### Costs by stop distance\n")
    w("Spread and slippage are fixed in points, so they cost more R the tighter the stop. "
      "Stop distance in USD per ounce at entry, buckets fixed in advance (not fitted).\n")
    edges = ((0, 3), (3, 6), (6, 12), (12, 25), (25, 10**9))
    rows = []
    for v in RUNS:
        groups = defaultdict(list)
        for period in PERIODS:
            for t in trades[(v, period)]:
                d = t.features["stop_usd"]
                edge = next(e for e in edges if e[0] <= d < e[1])
                groups[edge].append(t)
        for lo, hi in edges:
            ts = groups[(lo, hi)]
            if not ts:
                continue
            name = f"${lo}+" if hi > 10**8 else f"${lo}-{hi}"
            rows.append([v, name, str(len(ts)), f"{statistics.fmean(t.gross_r for t in ts):+.3f}",
                         f"{statistics.fmean(t.gross_r - t.r for t in ts):.3f}",
                         f"{statistics.fmean(t.r for t in ts):+.3f}",
                         fmt(pf([t.gross_r for t in ts])), fmt(pf([t.r for t in ts]))])  # fmt: skip
    w(table(["Ver", "Stop distance", "Trades (all periods)", "Gross R/trade", "Cost R/trade",
             "Net R/trade", "Gross PF (R)", "Net PF (R)"], rows))  # fmt: skip
    w("")

    # 6. reliability ---------------------------------------------------------------------------
    w("## 6. Statistical reliability\n")
    rows = []
    for v in RUNS:
        for period in PERIODS:
            ts = trades[(v, period)]
            rs = [t.r for t in ts]
            mean, lo, hi = mean_ci(rs)
            events = Counter(t.features["pullback_event"] for t in ts)
            repeated = sum(c for c in events.values() if c > 1)
            top = sorted(rs, reverse=True)
            without_top10 = sum(top[10:])
            months = defaultdict(float)
            for t in ts:
                months[t.entry.strftime("%Y-%m")] += t.r
            worst = sorted(months.items(), key=lambda kv: kv[1])[:3]
            losing_months = sum(1 for x in months.values() if x < 0)
            rows.append([
                v, LABEL[period], str(len(rs)), f"{mean:+.3f} [{lo:+.3f}, {hi:+.3f}]",
                f"{len(events)} ({repeated} trades share one)", f"{sum(rs):+.1f}",
                f"{without_top10:+.1f}", f"{losing_months} of {len(months)}",
                ", ".join(f"{m} {x:+.1f}" for m, x in worst),
            ])  # fmt: skip
    w(table(["Ver", "Period", "Trades", "Mean R [95% CI]", "Distinct pullbacks",
             "Sum R", "Sum R without best 10", "Losing months",
             "Worst 3 months (R)"], rows))  # fmt: skip
    w("\nVersion 1.0 trades the Version 1.1 rule would have rejected, and those it keeps "
      "(same Version 1.0 trade list, so the comparison is not affected by path changes):\n")
    rows = []
    for period in PERIODS:
        ts = trades[("1.0", period)]
        removed = [t for t in ts if gate.check(_direction(t), t.entry) is not None]
        kept = [t for t in ts if gate.check(_direction(t), t.entry) is None]
        rows.append([LABEL[period], "rejected by 1.1", *row_stats(removed)])
        rows.append([LABEL[period], "kept by 1.1", *row_stats(kept)])
    w(table(["Period", "Group", "Trades", "Win rate", "Mean R [95% CI]", "Sum R", "PF (R)",
             "Max DD (R)"], rows))  # fmt: skip
    w("")
    w("Risk-rejected signals (minimum volume above 2% of the balance) from the reports:\n")
    rows = []
    for v in RUNS:
        for period in PERIODS:
            rep = manifests[v]["results"][base_label(manifests[v])][period]
            rows.append([v, LABEL[period], str(rep["signals"]), str(rep["executable"]),
                         str(rep["minimum_volume_rejections"]),
                         str(rep["executable_at_minimum_volume"]),
                         f"£{float(rep['final_balance']):,.2f}"])  # fmt: skip
    w(table(["Ver", "Period", "Signal candles", "Executable", "Rejected: minimum volume",
             "Executed at 0.01 lot", "Final balance"], rows))  # fmt: skip
    w("")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT} at {datetime.now(UTC).isoformat(timespec='seconds')}")


def _direction(t: Trade) -> Direction:
    return Direction.BUY if t.direction == "buy" else Direction.SELL


if __name__ == "__main__":
    main()
