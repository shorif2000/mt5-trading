"""Reference levels shared by the candidate strategies (docs/research/xauusd-strategy-
candidates.md, common definitions and Amendment 1). Every value at a moment uses only bars that
had completed by then.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from trading.analysis.indicators import atr_series
from trading.backtest.bars import Bar
from trading.market_data.sessions import MarketCalendar

NEW_YORK = ZoneInfo("America/New_York")
SYMBOL = "XAUUSD"
M15 = timedelta(minutes=15)
ASIAN_START, ASIAN_LAST_OPEN = time(19, 0), time(1, 45)  # 19:00 (d-1) to the 01:45 bar of d
ASIAN_BARS = 28


def trading_day(moment: datetime) -> date:
    """Gold trading day: 18:00 New York opens the next day."""
    return (moment.astimezone(NEW_YORK) + timedelta(hours=6)).date()


def ny_time(moment: datetime) -> time:
    return moment.astimezone(NEW_YORK).time()


@dataclass(frozen=True)
class Day:
    day: date
    first: int  # index of the first M15 bar of the trading day
    last: int  # index of the last M15 bar
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class AsianRange:
    high: float
    low: float
    first: int
    last: int  # index of the 01:45 bar


class Levels:
    def __init__(self, m15: Sequence[Bar], calendar: MarketCalendar) -> None:
        self.m15, self.calendar = m15, calendar
        self.atr15 = atr_series([b.high for b in m15], [b.low for b in m15],
                                [b.close for b in m15], 14)  # fmt: skip
        self.days: list[Day] = []
        start = 0
        for i in range(1, len(m15) + 1):
            if i == len(m15) or trading_day(m15[i].open_time) != trading_day(m15[start].open_time):
                bars = m15[start:i]
                self.days.append(Day(trading_day(m15[start].open_time), start, i - 1,
                                     max(b.high for b in bars), min(b.low for b in bars),
                                     bars[-1].close))  # fmt: skip
                start = i
        self.day_index = {d.day: k for k, d in enumerate(self.days)}
        daily_atr = atr_series([d.high for d in self.days], [d.low for d in self.days],
                               [d.close for d in self.days], 14)  # fmt: skip
        # ADR on day k = ATR(14) of completed days up to k-1.
        self.adr: dict[date, float | None] = {
            d.day: (daily_atr[k - 1] if k >= 1 else None) for k, d in enumerate(self.days)
        }

    def complete(self, first: int, last: int, step: timedelta = M15) -> bool:
        """True when no bar is missing between ``first`` and ``last`` while the market was
        scheduled to be open (the Version 1.0 completeness rule)."""
        for previous, current in zip(self.m15[first:last], self.m15[first + 1 : last + 1],
                                     strict=False):  # fmt: skip
            missing = self.calendar.open_time(SYMBOL, previous.open_time + step, current.open_time)
            if missing > self.calendar.max_unexplained_gap:
                return False
        return True

    def asian_range(self, day: date) -> AsianRange | None:
        """Asian range of trading day ``day`` if all 28 bars (19:00 to 01:45) exist."""
        k = self.day_index.get(day)
        if k is None:
            return None
        d = self.days[k]
        idx = [i for i in range(d.first, d.last + 1)
               if self._in_asian(self.m15[i].open_time)]  # fmt: skip
        if len(idx) != ASIAN_BARS or idx[-1] - idx[0] != ASIAN_BARS - 1:
            return None
        bars = [self.m15[i] for i in idx]
        return AsianRange(max(b.high for b in bars), min(b.low for b in bars), idx[0], idx[-1])

    @staticmethod
    def _in_asian(moment: datetime) -> bool:
        t = ny_time(moment)
        return t >= ASIAN_START or t <= ASIAN_LAST_OPEN

    def previous_day(self, day: date) -> Day | None:
        k = self.day_index.get(day)
        return self.days[k - 1] if k else None

    def adr_ratio(self, day: date, lookback: int = 60) -> float | None:
        """ADR on ``day`` ÷ median ADR of the previous ``lookback`` trading days."""
        k = self.day_index.get(day)
        adr = self.adr.get(day)
        if k is None or adr is None or k < lookback:
            return None
        history = sorted(a for d in self.days[k - lookback : k] if (a := self.adr[d.day]))
        return adr / history[len(history) // 2] if history else None


def adx_series(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
               period: int = 14) -> list[float | None]:  # fmt: skip
    """Wilder's ADX. The value at index i uses bars up to i only; None until 2*period-1 bars."""
    n = len(closes)
    out: list[float | None] = [None] * n
    if n < 2 * period:
        return out
    tr, plus, minus = [0.0] * n, [0.0] * n, [0.0] * n
    for i in range(1, n):
        up, down = highs[i] - highs[i - 1], lows[i - 1] - lows[i]
        plus[i] = up if up > down and up > 0 else 0.0
        minus[i] = down if down > up and down > 0 else 0.0
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    s_tr, s_plus, s_minus = sum(tr[1 : period + 1]), sum(plus[1 : period + 1]), sum(
        minus[1 : period + 1])  # fmt: skip
    dx: list[float] = []
    adx: float | None = None
    for i in range(period, n):
        if i > period:
            s_tr += tr[i] - s_tr / period
            s_plus += plus[i] - s_plus / period
            s_minus += minus[i] - s_minus / period
        di_plus = 100 * s_plus / s_tr if s_tr else 0.0
        di_minus = 100 * s_minus / s_tr if s_tr else 0.0
        total = di_plus + di_minus
        value = 100 * abs(di_plus - di_minus) / total if total else 0.0
        if adx is None:
            dx.append(value)
            if len(dx) == period:
                adx = sum(dx) / period
                out[i] = adx
        else:
            adx = (adx * (period - 1) + value) / period
            out[i] = adx
    return out
