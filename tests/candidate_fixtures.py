"""Synthetic gold days for the candidate-strategy tests (New York trading hours, M15 bars)."""

import math
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from trading.backtest.bars import Bar

NY = ZoneInfo("America/New_York")
M15 = timedelta(minutes=15)


def trading_days(first: date, count: int) -> list[date]:
    days, d = [], first
    while len(days) < count:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def day_bars(day: date, price=lambda t: 2000.0, asian=0.3, other=1.0, spread=20) -> list[Bar]:
    """Trading day ``day``: 18:00 New York on the previous calendar day to the 16:45 bar.
    Asian bars (19:00-01:45) span +/-``asian`` around ``price``, others +/-``other``."""
    start = datetime.combine(day - timedelta(days=1), time(18, 0), tzinfo=NY)
    bars = []
    for i in range(92):  # 18:00 .. 16:45 = 23 hours
        t = start + i * M15
        ny = t.time()
        p = price(t)
        half = asian if (ny >= time(19, 0) or ny <= time(1, 45)) else other
        bars.append(Bar(t.astimezone(UTC), p, p + half, p - half, p, spread))
    return bars


def history(days: list[date], **kwargs) -> list[Bar]:
    return [b for d in days for b in day_bars(d, **kwargs)]


def replace(bars: list[Bar], at: datetime, **values: float) -> list[Bar]:
    out = []
    for b in bars:
        if b.open_time == at.astimezone(UTC):
            fields = {"open": b.open, "high": b.high, "low": b.low, "close": b.close, **values}
            b = Bar(b.open_time, spread_points=b.spread_points, **fields)
        out.append(b)
    return out


def h1_from(m15: list[Bar]) -> list[Bar]:
    groups: dict[datetime, list[Bar]] = {}
    for b in m15:
        groups.setdefault(b.open_time.replace(minute=0), []).append(b)
    return [
        Bar(
            t,
            g[0].open,
            max(x.high for x in g),
            min(x.low for x in g),
            g[-1].close,
            g[0].spread_points,
        )
        for t, g in sorted(groups.items())
    ]


def sine(period_hours: float, amplitude: float, centre: float = 2000.0):
    def price(t: datetime) -> float:
        hours = t.timestamp() / 3600
        return centre + amplitude * math.sin(2 * math.pi * hours / period_hours)

    return price
