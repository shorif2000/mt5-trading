"""Trade statistics for research reports, on both ledgers.

- Fixed risk: each trade's result in R (net ÷ its estimated loss at sizing); GBP = R × £20,
  i.e. 2% of a constant £1,000. Account-size effects do not move these figures.
- Compounding: the GBP results and running balance the engine produced.

Results are descriptive. A positive mean is never called "profitable" here.
"""

import random
import statistics
from collections import Counter
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from trading.backtest.engine import TradeRecord

FIXED_RISK_GBP = Decimal(20)  # 2% of a constant £1,000
SEED = 20261111


def r_net(t: TradeRecord) -> float:
    if not t.estimated_loss:
        raise ValueError(f"trade at {t.entry_time} has no estimated loss for R")
    return float(t.net_gbp / t.estimated_loss)


def r_gross(t: TradeRecord) -> float:
    if not t.estimated_loss:
        raise ValueError(f"trade at {t.entry_time} has no estimated loss for R")
    return float(t.gross_gbp / t.estimated_loss)


def profit_factor(values: Sequence[float]) -> float | None:
    gains = sum(v for v in values if v > 0)
    losses = -sum(v for v in values if v <= 0)
    return gains / losses if losses > 0 else None


def max_drawdown(values: Sequence[float]) -> float:
    peak = total = worst = 0.0
    for v in values:
        total += v
        peak = max(peak, total)
        worst = max(worst, peak - total)
    return worst


def bootstrap_mean(values: Sequence[float], draws: int = 2000) -> tuple[float, float, float]:
    """Mean and 95% bootstrap interval; trades resampled independently (this overstates
    precision when outcomes are serially dependent)."""
    if not values:
        return float("nan"), float("nan"), float("nan")
    rng = random.Random(SEED)
    n = len(values)
    means = sorted(sum(rng.choices(values, k=n)) / n for _ in range(draws))
    return statistics.fmean(values), means[int(0.025 * draws)], means[int(0.975 * draws)]


def _longest(values: Sequence[float], win: bool) -> int:
    best = run = 0
    for v in values:
        run = run + 1 if (v > 0) == win else 0
        best = max(best, run)
    return best


def summarise(
    trades: Sequence[TradeRecord],
    starting_balance: Decimal,
    events: int | None = None,
) -> dict[str, Any]:
    """Both ledgers for one group of trades in time order."""
    rs = [r_net(t) for t in trades]
    gross = [r_gross(t) for t in trades]
    nets = [float(t.net_gbp) for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    mean, lo, hi = bootstrap_mean(rs)
    top = sorted(rs, reverse=True)
    balance, peak, dd_gbp, dd_pct = float(starting_balance), float(starting_balance), 0.0, 0.0
    for t in trades:
        balance = float(t.balance_after)
        peak = max(peak, balance)
        if peak - balance > dd_gbp:
            dd_gbp, dd_pct = peak - balance, (peak - balance) / peak * 100
    n = len(trades)
    return {
        "trades": n,
        "events": events,
        "win_rate": len(wins) / n if n else None,
        "fixed_risk": {
            "net_r_per_trade": mean if n else None,
            "net_r_ci95": [lo, hi] if n else None,
            "gross_r_per_trade": statistics.fmean(gross) if n else None,
            "sum_r": sum(rs),
            "sum_r_without_best_10": sum(top[10:]),
            "average_win_r": statistics.fmean(wins) if wins else None,
            "average_loss_r": statistics.fmean(losses) if losses else None,
            "profit_factor": profit_factor(rs),
            "gross_profit_factor": profit_factor(gross),
            "max_drawdown_r": max_drawdown(rs),
            "net_gbp": sum(rs) * float(FIXED_RISK_GBP),
            "max_consecutive_losses": _longest(rs, win=False),
            "max_consecutive_wins": _longest(rs, win=True),
        },
        "compounding": {
            "net_gbp": sum(nets),
            "gross_gbp": float(sum((t.gross_gbp for t in trades), Decimal(0))),
            "profit_factor": profit_factor(nets),
            "average_win_gbp": statistics.fmean([x for x in nets if x > 0]) if wins else None,
            "average_loss_gbp": statistics.fmean([x for x in nets if x <= 0]) if losses else None,
            "max_drawdown_gbp": dd_gbp,
            "max_drawdown_percent": dd_pct,
            "final_balance": float(trades[-1].balance_after) if trades else float(starting_balance),
        },
        "costs_gbp": {
            "spread": float(sum((t.spread_cost_gbp for t in trades), Decimal(0))),
            "entry_slippage": float(sum((t.entry_slippage_gbp for t in trades), Decimal(0))),
            "exit_slippage": float(sum((t.exit_slippage_gbp for t in trades), Decimal(0))),
            "commission": float(sum((t.commission_gbp for t in trades), Decimal(0))),
            "swap": 0.0,  # no position is held overnight (forced close 16:45 New York)
        },
        "cost_r_per_trade": statistics.fmean(g - r for g, r in zip(gross, rs, strict=True))
        if n
        else None,
        "exits": dict(Counter(t.exit_reason for t in trades).most_common()),
    }


def fmt(value: float | None, digits: int = 3, signed: bool = True) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.{digits}f}" if signed else f"{value:.{digits}f}"
