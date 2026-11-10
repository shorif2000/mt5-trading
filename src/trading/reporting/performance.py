"""Basic descriptive performance calculations for closed-trade research data."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PerformanceSummary:
    trade_count: int
    net_profit: float
    win_rate: float
    profit_factor: float | None


def summarise_results(pnls: list[float]) -> PerformanceSummary:
    wins = sum(value for value in pnls if value > 0)
    losses = abs(sum(value for value in pnls if value < 0))
    count = len(pnls)
    return PerformanceSummary(
        trade_count=count,
        net_profit=sum(pnls),
        win_rate=(sum(value > 0 for value in pnls) / count) if count else 0.0,
        profit_factor=(wins / losses) if losses else (None if wins == 0 else float("inf")),
    )
