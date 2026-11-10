"""Exposure summaries. Correlation and currency aggregation require verified conversion data."""

from collections import defaultdict

from trading.models import Position


def open_volume_by_symbol(positions: list[Position]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for position in positions:
        totals[position.symbol] += position.volume
    return dict(totals)


def floating_pnl(positions: list[Position]) -> float:
    return sum(position.profit_account_currency for position in positions)
