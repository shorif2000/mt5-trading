"""Exposure summaries. Correlation and currency aggregation require verified conversion data."""

from collections import defaultdict
from dataclasses import dataclass

from trading.models import Direction, MarketSnapshot, Position


def open_volume_by_symbol(positions: list[Position]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for position in positions:
        totals[position.symbol] += position.volume
    return dict(totals)


def floating_pnl(positions: list[Position]) -> float:
    return sum(position.profit_account_currency for position in positions)


@dataclass(frozen=True)
class SymbolExposure:
    """Existing exposure in one symbol, reported alongside a sizing result. It is not
    netted against the per-trade limit, which is not a portfolio-wide limit."""

    symbol: str
    open_positions: int
    buy_volume: float
    sell_volume: float
    positions_without_stop_loss: int
    pending_orders: int
    pending_volume: float
    account_open_positions: int
    account_pending_orders: int


def symbol_exposure(snapshot: MarketSnapshot, symbol: str) -> SymbolExposure:
    positions = [p for p in snapshot.positions if p.symbol == symbol]
    orders = [o for o in snapshot.pending_orders if o.symbol == symbol]
    return SymbolExposure(
        symbol=symbol,
        open_positions=len(positions),
        buy_volume=sum(p.volume for p in positions if p.direction == Direction.BUY),
        sell_volume=sum(p.volume for p in positions if p.direction == Direction.SELL),
        positions_without_stop_loss=sum(1 for p in positions if p.stop_loss is None),
        pending_orders=len(orders),
        pending_volume=sum(o.volume for o in orders),
        account_open_positions=len(snapshot.positions),
        account_pending_orders=len(snapshot.pending_orders),
    )
