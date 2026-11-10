"""XAUUSD M15 intraday trend pullback, Version 1.0 (docs/strategy-xauusd-trend-pullback.md).

Signal rules only: trend (H1), pullback and confirmation (M15), stop and target. Filters,
sizing, margin, fills and exits belong to the backtest engine. Indicator series are computed
once; the value at an index uses only bars up to that index, and an H1 bar counts only once it
has closed, so nothing looks ahead.
"""

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from trading.analysis.indicators import atr_series, ema_series
from trading.backtest.bars import Bar
from trading.models import Direction

M15 = timedelta(minutes=15)
H1 = timedelta(hours=1)


@dataclass(frozen=True)
class PullbackParameters:
    """Approved Version 1.0 values (Appendix A interpretations included)."""

    h1_fast_ema: int = 50
    h1_slow_ema: int = 200
    h1_slope_bars: int = 5
    m15_ema: int = 20
    atr_period: int = 14
    touch_atr_fraction: float = 0.25  # A.B: "towards" EMA 20
    pullback_max_bars: int = 8  # A.B / A.D
    stop_buffer_atr: float = 0.2
    max_stop_atr: float = 3.0  # A.E: "excessively wide"
    target_r: float = 2.0  # A.F: in price distance
    max_spread_points: int = 35  # A.K
    h1_warmup_bars: int = 250  # A.L
    m15_warmup_bars: int = 50  # A.L


@dataclass(frozen=True)
class Setup:
    direction: Direction
    signal_index: int  # completed M15 bar that confirmed the entry
    stop: Decimal  # rounded to the tick, away from the entry
    pullback_extreme: float
    atr: float  # M15 ATR at the signal bar
    # Reporting only: index of the first bar of the contiguous run of pullback bars that the
    # latest touch belongs to. Signal candles from the same pullback share it.
    pullback_event_start: int = -1


def round_away(price: float, tick: Decimal, direction: Direction) -> Decimal:
    """A long stop rounds down, a short stop up: never closer to the entry."""
    value = Decimal(str(price)) / tick
    rounding = ROUND_FLOOR if direction == Direction.BUY else ROUND_CEILING
    return value.to_integral_value(rounding=rounding) * tick


def target_price(entry: Decimal, stop: Decimal, r: float, tick: Decimal) -> Decimal:
    """Entry plus r times the entry-stop distance, rounded towards the entry (conservative)."""
    distance = abs(entry - stop) * Decimal(str(r))
    if entry > stop:  # long
        return ((entry + distance) / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
    return ((entry - distance) / tick).to_integral_value(rounding=ROUND_CEILING) * tick


class XauusdM15Pullback:
    def __init__(
        self, m15: Sequence[Bar], h1: Sequence[Bar], tick_size: Decimal,
        params: PullbackParameters | None = None,
    ) -> None:  # fmt: skip
        self.params = p = params or PullbackParameters()
        self.m15, self.h1, self.tick = m15, h1, tick_size
        self.h1_close_times = [bar.open_time + H1 for bar in h1]
        h1_closes = [bar.close for bar in h1]
        self.h1_fast = ema_series(h1_closes, p.h1_fast_ema)
        self.h1_slow = ema_series(h1_closes, p.h1_slow_ema)
        self.m15_ema = ema_series([bar.close for bar in m15], p.m15_ema)
        self.m15_atr = atr_series(
            [b.high for b in m15], [b.low for b in m15], [b.close for b in m15], p.atr_period
        )

    def last_completed_h1(self, moment: datetime) -> int | None:
        """Index of the last H1 bar that had closed by ``moment``."""
        index = bisect_right(self.h1_close_times, moment) - 1
        return index if index >= 0 else None

    def trend(self, h1_index: int | None) -> Direction | None:
        p = self.params
        if h1_index is None or h1_index + 1 < p.h1_warmup_bars:
            return None
        then = h1_index - p.h1_slope_bars
        fast, slow = self.h1_fast[h1_index], self.h1_slow[h1_index]
        earlier = self.h1_fast[then] if then >= 0 else None
        if fast is None or slow is None or earlier is None:
            return None
        close = self.h1[h1_index].close
        if fast > slow and fast > earlier and close > fast:
            return Direction.BUY
        if fast < slow and fast < earlier and close < fast:
            return Direction.SELL
        return None

    def trend_at(self, moment: datetime) -> Direction | None:
        return self.trend(self.last_completed_h1(moment))

    def _touches(self, j: int, direction: Direction) -> bool:
        ema_j, atr_j = self.m15_ema[j], self.m15_atr[j]
        if ema_j is None or atr_j is None:
            return False
        reach = self.params.touch_atr_fraction * atr_j
        if direction == Direction.BUY:
            return self.m15[j].low <= ema_j + reach
        return self.m15[j].high >= ema_j - reach

    def _event_start(self, latest_touch: int, direction: Direction) -> int:
        start = latest_touch
        while start > 0 and self._touches(start - 1, direction):
            start -= 1
        return start

    def evaluate(self, index: int) -> Setup | None:
        """Entry conditions 1-6 at the completed M15 bar ``index`` (7, one position, is the
        engine's). Returns None when there is no setup."""
        p = self.params
        if index < max(p.m15_warmup_bars, p.pullback_max_bars + 1):
            return None
        bar, previous = self.m15[index], self.m15[index - 1]
        ema, atr = self.m15_ema[index], self.m15_atr[index]
        if ema is None or atr is None:
            return None
        direction = self.trend_at(bar.open_time + M15)
        if direction is None:
            return None
        window = range(index - p.pullback_max_bars, index)
        touches = []
        for j in window:
            ema_j, atr_j = self.m15_ema[j], self.m15_atr[j]
            if ema_j is None or atr_j is None:
                return None
            reach = p.touch_atr_fraction * atr_j
            if direction == Direction.BUY and self.m15[j].low <= ema_j + reach:
                touches.append(j)
            if direction == Direction.SELL and self.m15[j].high >= ema_j - reach:
                touches.append(j)
        if not touches:
            return None
        if direction == Direction.BUY:
            confirmed = bar.close > ema and bar.close > previous.high and bar.close > bar.open
            extreme = min(self.m15[j].low for j in range(touches[0], index + 1))
            stop_price = extreme - p.stop_buffer_atr * atr
        else:
            confirmed = bar.close < ema and bar.close < previous.low and bar.close < bar.open
            extreme = max(self.m15[j].high for j in range(touches[0], index + 1))
            stop_price = extreme + p.stop_buffer_atr * atr
        if not confirmed:
            return None
        return Setup(
            direction,
            index,
            round_away(stop_price, self.tick, direction),
            extreme,
            atr,
            pullback_event_start=self._event_start(touches[-1], direction),
        )
