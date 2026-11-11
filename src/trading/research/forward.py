"""Strategy A forward observation (EXP-011): frozen-specification check, completed-bar handling
and forward signal records. Read-only research; nothing here can place or change orders.
"""

import hashlib
import json
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from trading.backtest.bars import Bar
from trading.research.candidates import StrategyA
from trading.research.levels import trading_day

# The gold trading week that opens Sunday 2026-11-15 18:00 New York (23:00 UTC): trading day
# 2026-11-16 (programme Amendment 1, A1.1). Earlier data is never forward evidence.
FORWARD_START = datetime(2026, 11, 15, 23, 0, tzinfo=UTC)
FREEZE_RECORD = Path("docs/research/strategy-a-freeze.json")
# Everything that decides a Strategy A signal, its filters, sizing, costs and evaluation.
FROZEN_FILES = (
    "docs/research/xauusd-strategy-candidates.md",
    "docs/research/strategy-a-forward-test.md",
    "src/trading/research/forward.py",
    "src/trading/research/candidates.py",
    "src/trading/research/levels.py",
    "src/trading/research/candidate_engine.py",
    "src/trading/research/news.py",
    "src/trading/research/stats.py",
    "src/trading/backtest/engine.py",
    "src/trading/strategies/xauusd_m15_pullback.py",
    "src/trading/analysis/indicators.py",
    "src/trading/risk/position_sizing.py",
    "src/trading/risk/margin.py",
    "src/trading/risk/sizing_config.py",
    "config/risk.yaml",
    "config/backtest.yaml",
    "config/market_sessions.yaml",
)
M15 = timedelta(minutes=15)


def digest(paths: Iterable[str] = FROZEN_FILES) -> dict[str, str]:
    return {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths}


def freeze_mismatches(record: Path = FREEZE_RECORD) -> list[str]:
    """Frozen files whose content differs from the freeze record (empty when intact)."""
    frozen = json.loads(record.read_text(encoding="utf-8"))["files"]
    current = digest(frozen)
    return sorted(p for p, sha in frozen.items() if current[p] != sha)


def completed(bars: Sequence[Bar], now: datetime, step: timedelta = M15) -> list[Bar]:
    """Bars that had closed by ``now``; the bar still forming is never used."""
    return [b for b in bars if b.open_time + step <= now]


def merge_rows(stored: Iterable[dict[str, Any]], fresh: Iterable[dict[str, Any]]
               ) -> list[dict[str, Any]]:  # fmt: skip
    """Bars by broker time; a fresh copy of a bar replaces the stored one."""
    rows = {r["time"]: r for r in stored}
    rows.update({r["time"]: r for r in fresh})
    return [rows[t] for t in sorted(rows)]


def forward_signals(strategy: StrategyA, start: datetime = FORWARD_START) -> list[dict[str, Any]]:
    """Strategy A signals whose signal bar closed at or after ``start``, one per event."""
    m = strategy.m15
    out = []
    for j, signal in sorted(strategy.signals.items()):
        close = m[j].open_time + M15
        if close < start:
            continue
        setup = signal.setup
        out.append({
            "signal_close_utc": close.isoformat(),
            "entry_time_utc": close.isoformat(),  # next bar's open
            "trading_day": trading_day(m[j].open_time).isoformat(),
            "direction": setup.direction.value,
            "level": signal.level,
            "breakout_bar_utc": m[setup.pullback_event_start].open_time.isoformat(),
            "stop": str(setup.stop),
            "atr15": setup.atr,
            "signal_bar": {"open": m[j].open, "high": m[j].high, "low": m[j].low,
                           "close": m[j].close, "spread_points": m[j].spread_points},
        })  # fmt: skip
    return out


# --- pre-registered forward evaluation (EXP-011) ------------------------------------------

MIN_EVENTS = 100
MIN_WEEKS = 26
FINAL_DEADLINE = datetime(2028, 11, 15, tzinfo=UTC)
CI_LEVEL = 0.975  # two arms are evaluated: 97.5% intervals (Bonferroni for 2)


def readiness(events: int, as_of: datetime, start: datetime = FORWARD_START) -> str:
    """Whether an arm may be evaluated yet. Interim reports are descriptive only."""
    weeks = (as_of - start).days / 7
    if events >= MIN_EVENTS and weeks >= MIN_WEEKS:
        return "READY FOR EVALUATION"
    if as_of >= FINAL_DEADLINE:
        return "FINAL: INSUFFICIENT DATA (deadline reached)"
    return (f"NOT READY: {events} of {MIN_EVENTS} events, {weeks:.1f} of {MIN_WEEKS} weeks; "
            "results below are descriptive only")  # fmt: skip


def evaluate(
    net_r: Sequence[float],
    gross_r: Sequence[float],
    stress_net_r: Sequence[float],
    tercile_net_r: dict[str, Sequence[float]],
) -> dict[str, Any]:
    """The pre-registered forward criteria for one arm (base scenario, fixed risk, news on).
    Meeting all of them is evidence for the hypothesis, never a trading recommendation."""
    from statistics import fmean  # noqa: PLC0415

    from trading.research.stats import bootstrap_mean  # noqa: PLC0415

    mean, lo, hi = bootstrap_mean(net_r, level=CI_LEVEL)
    top = sorted(net_r, reverse=True)
    terciles = {k: fmean(v) for k, v in tercile_net_r.items() if v}
    checks = {
        "gross_positive": bool(gross_r) and fmean(gross_r) > 0,
        "net_positive": bool(net_r) and mean > 0,
        "ci_lower_above_zero": bool(net_r) and lo > 0,
        "without_best_10_positive": sum(top[10:]) > 0,
        "stress_40pt_positive": bool(stress_net_r) and fmean(stress_net_r) > 0,
        "two_of_three_terciles_positive": sum(v > 0 for v in terciles.values()) >= 2,
    }
    if all(checks.values()):
        outcome = (
            "SUPPORTED ON FORWARD DATA (evidence only; any execution needs a separate "
            "authorised decision with independent risk controls and demo validation)"
        )
    elif net_r and hi < 0:
        outcome = "NEGATIVE"
    else:
        outcome = "INCONCLUSIVE"
    return {"net_r": [mean, lo, hi], "ci_level": CI_LEVEL, "terciles": terciles,
            "checks": checks, "outcome": outcome}  # fmt: skip
