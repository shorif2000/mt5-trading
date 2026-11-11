"""Read-only quote observations around a modelled entry, from historical bid/ask ticks.

This does **not** measure execution slippage: no order is sent. It measures how the executable
quote (the ask for a buy, the bid for a sell) moves in the seconds after the moment the
backtest assumes a market entry (the open of the bar after the signal), and how far the
backtest's bar model (bar open + bar spread) is from the first real quote. That quantifies the
uncertainty in the entry-cost assumption (scenarios of 0, 7 and 40 points).

Positive "adverse" values are against the trade: a higher ask for a buy, a lower bid for a sell.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from trading.models import Direction
from trading.research.breakeven import Tick

OFFSETS_SECONDS = (0.5, 1.0, 2.0, 5.0, 15.0, 60.0, 300.0)


@dataclass(frozen=True)
class QuoteObservation:
    entry_time: datetime  # the modelled entry: open of the bar after the signal bar
    direction: Direction
    pre_entry_bid: Decimal | None  # last quote before the entry moment
    pre_entry_ask: Decimal | None
    first_tick_time: datetime
    first_executable: Decimal  # first quote at or after the entry moment
    first_spread_points: Decimal
    model_executable: Decimal  # the backtest's entry: bar open (bid) + bar spread for a buy
    model_minus_first_points: Decimal  # >0: the model entry was worse than the first quote
    adverse_points: dict[float, Decimal | None]  # executable at entry + offset vs first quote
    spread_points: dict[float, Decimal | None]
    max_adverse_points_5s: Decimal | None  # worst executable quote within 5 seconds

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {k: getattr(self, k) for k in (
            "pre_entry_bid", "pre_entry_ask", "first_executable", "first_spread_points",
            "model_executable", "model_minus_first_points", "max_adverse_points_5s")}  # fmt: skip
        out["entry_time"] = self.entry_time.isoformat()
        out["first_tick_time"] = self.first_tick_time.isoformat()
        out["direction"] = self.direction.value
        out["adverse_points"] = {str(k): _plain(v) for k, v in self.adverse_points.items()}
        out["spread_points"] = {str(k): _plain(v) for k, v in self.spread_points.items()}
        return {k: _plain(v) for k, v in out.items()}


def _plain(value: Any) -> Any:
    return format(value, "f") if isinstance(value, Decimal) else value


def observe(
    ticks: Sequence[Tick],
    entry_time: datetime,
    direction: Direction,
    bar_open_bid: Decimal,
    bar_spread_points: int,
    point: Decimal,
    window_end: datetime,
    max_first_delay: timedelta = timedelta(seconds=60),
) -> QuoteObservation | None:
    """Quote movement after ``entry_time`` from ``ticks`` fetched up to ``window_end``. None
    when no quote arrives within ``max_first_delay`` of the entry moment. The quote at an offset
    is the last tick at or before it; an offset beyond ``window_end`` is None (not filled in)."""
    ordered = sorted(ticks, key=lambda t: t.time)
    before = [t for t in ordered if t.time < entry_time]
    after = [t for t in ordered if t.time >= entry_time]
    if not after or after[0].time - entry_time > max_first_delay:
        return None
    buy = direction == Direction.BUY

    def executable(t: Tick) -> Decimal:
        return t.ask if buy else t.bid

    def adverse(price: Decimal, reference: Decimal) -> Decimal:
        return ((price - reference) if buy else (reference - price)) / point

    first = after[0]
    reference = executable(first)
    adverse_at: dict[float, Decimal | None] = {}
    spread_at: dict[float, Decimal | None] = {}
    for offset in OFFSETS_SECONDS:
        moment = entry_time + timedelta(seconds=offset)
        prevailing = [t for t in after if t.time <= moment]
        if moment > window_end or not prevailing:
            adverse_at[offset] = spread_at[offset] = None
            continue
        tick = prevailing[-1]
        adverse_at[offset] = adverse(executable(tick), reference)
        spread_at[offset] = (tick.ask - tick.bid) / point
    window = [t for t in after if t.time <= entry_time + timedelta(seconds=5)]
    worst = max((adverse(executable(t), reference) for t in window), default=None)
    if entry_time + timedelta(seconds=5) > window_end:
        worst = None
    model = bar_open_bid + bar_spread_points * point if buy else bar_open_bid
    return QuoteObservation(
        entry_time=entry_time,
        direction=direction,
        pre_entry_bid=before[-1].bid if before else None,
        pre_entry_ask=before[-1].ask if before else None,
        first_tick_time=first.time,
        first_executable=reference,
        first_spread_points=(first.ask - first.bid) / point,
        model_executable=model,
        model_minus_first_points=adverse(model, reference),
        adverse_points=adverse_at,
        spread_points=spread_at,
        max_adverse_points_5s=worst,
    )


# --- read-only tick download --------------------------------------------------------------

TickFetcher = Callable[[datetime, datetime], Any]  # async (start, end) -> list[Tick]


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


async def fetch_ticks(session: Any, clock: Any, live_offset: int, start: datetime,
                      end: datetime) -> list[Tick]:  # fmt: skip
    """Bid/ask ticks in [start, end) through a read-only MCP session (``call_read_only`` with
    ``get_ticks``). The server converts request times with today's broker offset, so each
    request is shifted to ask for the broker time that corresponds to ``start``; returned ticks
    are converted from raw broker milliseconds with the DST-aware ``BrokerClock``."""
    from trading.market_data.mcp_collector import call_read_only  # noqa: PLC0415

    cursor = start + timedelta(seconds=clock.offset_at(start) - live_offset)
    ticks: list[Tick] = []
    for _ in range(50):
        r = await call_read_only(session, "get_ticks", {
            "symbol": "XAUUSD", "start": _iso(cursor), "count": 5000, "flags": "INFO"},
            timeout=90)  # fmt: skip
        rows = r.get("ticks") or []
        if r.get("tool_error") or not rows:
            break
        last = start
        for row in rows:
            ms = row["time_msc"]
            utc = clock.utc(ms // 1000) + timedelta(milliseconds=ms % 1000)
            last = utc
            if start <= utc < end:
                ticks.append(Tick(utc, Decimal(str(row["bid"])), Decimal(str(row["ask"]))))
        if last >= end or len(rows) < 5000:
            break
        cursor = last + timedelta(milliseconds=1)
        cursor += timedelta(seconds=clock.offset_at(last) - live_offset)
    return ticks
