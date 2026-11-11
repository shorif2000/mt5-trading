"""Load downloaded MT5 history into validated UTC bars, with a coverage report."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from trading.backtest.bars import Bar
from trading.market_data.mcp_export import BrokerClock
from trading.market_data.sessions import MarketCalendar

TIMEFRAMES = {
    "M1": timedelta(minutes=1),
    "M15": timedelta(minutes=15),
    "H1": timedelta(hours=1),
}


@dataclass(frozen=True)
class Coverage:
    symbol: str
    timeframe: str
    bars: int
    first: datetime | None
    last: datetime | None
    gaps: tuple[tuple[datetime, datetime], ...]  # missing during scheduled market hours


def bars_from_rows(rows: list[dict[str, Any]], clock: BrokerClock, timeframe: str) -> list[Bar]:
    step = int(TIMEFRAMES[timeframe].total_seconds())
    bars = []
    for row in rows:
        epoch = row["time"]
        if not isinstance(epoch, int) or epoch % step:
            raise ValueError(f"bar time {epoch!r} is not aligned to {timeframe}")
        bars.append(
            Bar(
                clock.utc(epoch),
                float(row["open"]),
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
                int(row["spread"]),
            )
        )
    for previous, current in zip(bars, bars[1:], strict=False):
        if current.open_time <= previous.open_time:
            raise ValueError(f"bars are not strictly ascending at {current.open_time}")
    return bars


def coverage(symbol: str, timeframe: str, bars: list[Bar], calendar: MarketCalendar) -> Coverage:
    step = TIMEFRAMES[timeframe]
    gaps = tuple(
        (previous.open_time + step, current.open_time)
        for previous, current in zip(bars, bars[1:], strict=False)
        if calendar.open_time(symbol, previous.open_time + step, current.open_time)
        > calendar.max_unexplained_gap
    )
    return Coverage(
        symbol,
        timeframe,
        len(bars),
        bars[0].open_time if bars else None,
        bars[-1].open_time if bars else None,
        gaps,
    )


def load_history(
    path: Path, *, broker_timezone: str = "America/New_York", broker_shift_hours: int = 7
) -> dict[tuple[str, str], list[Bar]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    offset = data["terminal_status"]["broker_offset_seconds"]
    if (
        not isinstance(offset, int)
        or data["terminal_status"].get("broker_offset_confident") is not True
    ):
        raise ValueError("history was downloaded without a confident broker offset")
    clock = BrokerClock(broker_timezone, broker_shift_hours, offset)
    if clock.offset_at(datetime.fromisoformat(data["series"][0]["end"])) is None:
        raise ValueError("broker clock rule unusable")
    series = {}
    for item in data["series"]:
        if item["problems"]:
            raise ValueError(
                f"{item['symbol']} {item['timeframe']}: download problems {item['problems']}"
            )
        series[(item["symbol"], item["timeframe"])] = bars_from_rows(
            item["rates"], clock, item["timeframe"]
        )
    return series
