"""Candidate strategies A, C and B (docs/research/xauusd-strategy-candidates.md and its
Amendment 1), as fixed, machine-testable rules. Research only; nothing here can trade.

Each strategy scans the history once and emits **one signal per setup event** (the first
qualifying candle). It also keeps an event log with every event's stage and outcome for the
descriptive event studies. All values at a signal use only bars completed by its close.
Strategies do not read the economic calendar; the backtest applies the news filter.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from decimal import Decimal

from trading.analysis.indicators import atr_series
from trading.backtest.bars import Bar
from trading.market_data.sessions import MarketCalendar
from trading.models import Direction
from trading.research.levels import Levels, adx_series, ny_time, trading_day
from trading.strategies.xauusd_m15_pullback import Setup, round_away

BUY, SELL = Direction.BUY, Direction.SELL
H1 = timedelta(hours=1)


@dataclass(frozen=True)
class CandidateParams:
    """Engine-facing values shared with Version 1.0 (unchanged): spread cap, maximum stop in
    ATR15, and the 2R target for A and C."""

    max_spread_points: int = 35
    max_stop_atr: float = 3.0
    target_r: float = 2.0


@dataclass(frozen=True)
class CandidateSignal:
    setup: Setup  # pullback_event_start holds the event's anchor bar index
    event: tuple[str, int]  # (direction, anchor bar index): one per event
    target_price: float | None = None  # B: range midpoint (rounded at the fill)
    boundary: tuple[str, float] | None = None  # B: (side, boundary value) for stop-out blocks
    level: str = ""  # A/C: which reference level


@dataclass
class EventLog:
    day: date
    direction: str
    anchor: int  # breakout, sweep or first zone bar
    level: str
    stage: str  # final stage reached, e.g. "signal", "invalidated", "no retest"
    signal_index: int | None = None
    notes: list[str] = field(default_factory=list)


class Candidate:
    name = ""

    def __init__(self, m15: Sequence[Bar], h1: Sequence[Bar], calendar: MarketCalendar,
                 tick: Decimal) -> None:  # fmt: skip
        self.m15, self.h1, self.tick = m15, h1, tick
        self.params = CandidateParams()
        self.levels = Levels(m15, calendar)
        self.atr15 = self.levels.atr15
        self.signals: dict[int, CandidateSignal] = {}
        self.events: list[EventLog] = []
        self.scan()

    def scan(self) -> None:
        raise NotImplementedError

    def evaluate(self, index: int) -> Setup | None:
        signal = self.signals.get(index)
        return signal.setup if signal else None

    def _stop(self, direction: Direction, price: float) -> Decimal:
        return round_away(price, self.tick, direction)

    def _day_bars(self, day: date, start: time, last_open: time) -> list[int]:
        """Indices of trading day ``day`` whose New York open time is in [start, last_open],
        allowing windows that cross midnight (e.g. 19:00 to 13:45)."""
        k = self.levels.day_index.get(day)
        if k is None:
            return []
        d = self.levels.days[k]
        out = []
        for i in range(d.first, d.last + 1):
            t = ny_time(self.m15[i].open_time)
            inside = (start <= t <= last_open) if start <= last_open else (
                t >= start or t <= last_open)  # fmt: skip
            if inside:
                out.append(i)
        return out


# --- A: Asian-range breakout and retest -----------------------------------------------------


class StrategyA(Candidate):
    name = "A: session breakout and retest"
    BREAKOUT_FROM, LAST_SIGNAL_OPEN = time(2, 0), time(10, 45)
    WINDOW = 12

    def scan(self) -> None:
        m, atr = self.m15, self.atr15
        for d in self.levels.days:
            ar = self.levels.asian_range(d.day)
            adr = self.levels.adr.get(d.day)
            if ar is None or adr is None:
                continue
            width = ar.high - ar.low
            if not 0.15 * adr <= width <= 0.60 * adr:
                continue
            scan = self._day_bars(d.day, self.BREAKOUT_FROM, self.LAST_SIGNAL_OPEN)
            found: list[tuple[int, CandidateSignal, EventLog]] = []
            for direction in (BUY, SELL):
                level = ar.high if direction == BUY else ar.low
                sign = 1 if direction == BUY else -1
                b = next((i for i in scan if atr[i] is not None
                          and sign * (m[i].close - level) > 0.10 * atr[i]), None)  # type: ignore[operator]  # fmt: skip
                if b is None:
                    continue
                log = EventLog(d.day, direction.value, b, "Asian high" if sign > 0 else "Asian low",
                               "no retest")  # fmt: skip
                self.events.append(log)
                retested = False
                for j in range(b + 1, b + 1 + self.WINDOW):
                    if j >= len(m) or trading_day(m[j].open_time) != d.day:
                        log.stage = "window ended (day end)"
                        break
                    if ny_time(m[j].open_time) > self.LAST_SIGNAL_OPEN:
                        log.stage = "window ended (11:00)"
                        break
                    a, bar = atr[j], m[j]
                    if a is None:
                        log.stage = "data incomplete"
                        break
                    if sign * (bar.close - level) < -0.10 * a:  # invalidation first
                        log.stage = "invalidated (failed breakout)"
                        break
                    near = bar.low if direction == BUY else bar.high
                    if (sign * (near - level) <= 0.25 * a) and (sign * (near - level) >= -0.50 * a):
                        retested = True
                    mid = (bar.high + bar.low) / 2
                    confirmed = (sign * (bar.close - level) > 0
                                 and sign * (bar.close - bar.open) > 0
                                 and sign * (bar.close - mid) >= 0)  # fmt: skip
                    if retested and confirmed:
                        if not self.levels.complete(ar.first, j):
                            log.stage = "data incomplete"
                            break
                        extreme = (min(x.low for x in m[b : j + 1]) if direction == BUY
                                   else max(x.high for x in m[b : j + 1]))  # fmt: skip
                        stop = self._stop(direction, extreme - sign * 0.20 * a)
                        setup = Setup(direction, j, stop, extreme, a, pullback_event_start=b)
                        sig = CandidateSignal(setup, (direction.value, b), level=log.level)
                        log.stage, log.signal_index = "signal", j
                        found.append((j, sig, log))
                        break
                else:
                    if retested:
                        log.stage = "retest, no confirmation"
            # Priority (Amendment 1): the earlier signal bar takes the day's single trade.
            found.sort(key=lambda x: x[0])
            if len(found) == 2 and found[0][0] == found[1][0]:
                for _, _, log in found:
                    log.stage = "conflict (both sides on one bar)"
                continue
            for k, (j, sig, log) in enumerate(found):
                if k == 0:
                    self.signals[j] = sig
                else:
                    log.stage = "superseded (other side signalled first)"


# --- C: liquidity sweep and failed breakout -------------------------------------------------


class StrategyC(Candidate):
    name = "C: liquidity sweep and failed breakout"
    ENTRY_FIRST_OPEN, ENTRY_LAST_OPEN = time(1, 45), time(13, 45)
    PRIORITY = {"previous-day high": 0, "previous-day low": 0, "Asian high": 1, "Asian low": 1}

    def scan(self) -> None:
        by_bar: dict[int, list[tuple[CandidateSignal, EventLog]]] = defaultdict(list)
        for d in self.levels.days:
            prev = self.levels.previous_day(d.day)
            ar = self.levels.asian_range(d.day)
            levels: list[tuple[str, float, Direction, time, time]] = []
            if prev is not None:
                levels += [("previous-day high", prev.high, SELL, time(19, 0), time(13, 45)),
                           ("previous-day low", prev.low, BUY, time(19, 0),
                            time(13, 45))]  # fmt: skip
            if ar is not None:
                levels += [("Asian high", ar.high, SELL, time(2, 0), time(10, 45)),
                           ("Asian low", ar.low, BUY, time(2, 0), time(10, 45))]  # fmt: skip
            for name, level, direction, start, last in levels:
                result = self._sweep(d.day, name, level, direction, start, last)
                if result is not None:
                    by_bar[result[0].setup.signal_index].append(result)
        for j, items in sorted(by_bar.items()):
            directions = {sig.setup.direction for sig, _ in items}
            if len(directions) > 1:
                for _, log in items:
                    log.stage = "conflict (opposite signals on one bar)"
                continue
            items.sort(key=lambda x: self.PRIORITY[x[0].level])
            self.signals[j] = items[0][0]
            for _, log in items[1:]:
                log.stage = "duplicate (same bar, lower-priority level)"

    def _sweep(self, day: date, name: str, level: float, direction: Direction, start: time,
               last: time) -> tuple[CandidateSignal, EventLog] | None:  # fmt: skip
        """Short after a sweep of a high level (direction SELL); mirror for a low level."""
        m, atr = self.m15, self.atr15
        sign = 1 if direction == SELL else -1  # +1: the level is a high, price swept above it
        scan = self._day_bars(day, start, last)
        s = next((i for i in scan if atr[i] is not None
                  and sign * ((m[i].high if sign > 0 else m[i].low) - level) >= 0.10 * atr[i]),  # type: ignore[operator]
                 None)  # fmt: skip
        if s is None:
            return None
        bar, a = m[s], atr[s]
        assert a is not None
        log = EventLog(day, direction.value, s, name, "no reclaim")
        self.events.append(log)
        if sign * (bar.open - level) >= 0:
            log.stage = "opened beyond level"
            return None
        extreme_s = bar.high if sign > 0 else bar.low
        if sign * (extreme_s - level) > 1.50 * a:
            log.stage = "displacement, not a sweep"
            return None
        reclaim = None
        for r in range(s, s + 3):
            if r >= len(m) or trading_day(m[r].open_time) != day:
                break
            if r > s and sign * (m[r].close - extreme_s) > 0:
                log.stage = "invalidated (close beyond sweep extreme)"
                return None
            if sign * (m[r].close - level) < 0:
                reclaim = r
                break
        if reclaim is None:
            return None
        log.stage = "reclaimed, no confirmation"
        far = bar.low if sign > 0 else bar.high  # the sweep bar's opposite extreme
        for j in range(reclaim + 1, reclaim + 5):
            if j >= len(m) or trading_day(m[j].open_time) != day:
                log.stage = "window ended (day end)"
                return None
            c = m[j].close
            if sign * (c - extreme_s) > 0:
                log.stage = "invalidated (close beyond sweep extreme)"
                return None
            if sign * (c - far) < 0 and sign * (c - level) < 0:
                t = ny_time(m[j].open_time)
                if not (self.ENTRY_FIRST_OPEN <= t <= self.ENTRY_LAST_OPEN):
                    log.stage = "signal outside entry window"
                    return None
                aj = atr[j]
                if aj is None or not self.levels.complete(s, j):
                    log.stage = "data incomplete"
                    return None
                extreme = (max(x.high for x in m[s : j + 1]) if sign > 0
                           else min(x.low for x in m[s : j + 1]))  # fmt: skip
                stop = self._stop(direction, extreme + sign * 0.20 * aj)
                setup = Setup(direction, j, stop, extreme, aj, pullback_event_start=s)
                log.stage, log.signal_index = "signal", j
                return CandidateSignal(setup, (direction.value, s), level=name), log
        return None


# --- B: H1 range mean reversion -------------------------------------------------------------


@dataclass(frozen=True)
class Range:
    high: float
    low: float
    atr: float  # ATRH1 at the range's last H1 bar
    h1_index: int


class StrategyB(Candidate):
    name = "B: H1 range mean reversion"
    WINDOW, TOUCH, CLUSTER_GAP, VISIT_GAP = 48, 0.25, 6, 24

    def scan(self) -> None:
        h = self.h1
        self.atr_h1 = atr_series([b.high for b in h], [b.low for b in h], [b.close for b in h], 14)
        self.adx = adx_series([b.high for b in h], [b.low for b in h], [b.close for b in h], 14)
        self.ranges = self._ranges()
        h1_close = [b.open_time + H1 for b in h]
        m, atr = self.m15, self.atr15
        k = 0
        visits: dict[str, tuple[int, int, bool]] = {}  # side -> (start, last zone bar, traded)
        for i, bar in enumerate(m):
            close_time = bar.open_time + timedelta(minutes=15)
            while k + 1 < len(h1_close) and h1_close[k + 1] <= close_time:
                k += 1
            if h1_close[k] > close_time:
                continue
            rng, a = self.ranges.get(k), atr[i]
            if rng is None or a is None:
                continue
            for direction in (BUY, SELL):
                side = direction.value
                boundary = rng.low if direction == BUY else rng.high
                sign = 1 if direction == BUY else -1
                near = bar.low if direction == BUY else bar.high
                in_zone = sign * (near - boundary) <= self.TOUCH * rng.atr
                if not in_zone:
                    continue
                start, last, traded = visits.get(side, (i, i, False))
                if i - last > self.VISIT_GAP:
                    start, traded = i, False
                if start == i:
                    self.events.append(EventLog(trading_day(bar.open_time), side, i,
                                                "range low" if sign > 0 else "range high",
                                                "visit, no signal"))  # fmt: skip
                visits[side] = (start, i, traded)
                if traded:
                    continue
                spread = bar.high - bar.low
                rejection = (sign * (near - boundary) >= -0.50 * a
                             and sign * (bar.close - boundary) >= 0
                             and sign * (bar.close - bar.open) > 0 and spread > 0
                             and (sign * (bar.close - near)) >= 0.60 * spread)  # fmt: skip
                if not rejection:
                    continue
                if not self.levels.complete(max(0, i - 1), i):
                    continue
                extreme = min(bar.low, rng.low) if sign > 0 else max(bar.high, rng.high)
                stop = self._stop(direction, extreme - sign * 0.30 * a)
                setup = Setup(direction, i, stop, extreme, a, pullback_event_start=start)
                self.signals[i] = CandidateSignal(
                    setup, (side, start), target_price=(rng.high + rng.low) / 2,
                    boundary=(side, boundary),
                    level="range low" if sign > 0 else "range high")  # fmt: skip
                visits[side] = (start, i, True)
                log = next(e for e in reversed(self.events)
                           if e.anchor == start and e.direction == side)  # fmt: skip
                log.stage, log.signal_index = "signal", i

    def _ranges(self) -> dict[int, Range]:
        """Valid ranges by H1 index (completed bars only); a break blocks the window."""
        h, out = self.h1, {}
        raw: dict[int, tuple[float, float]] = {}
        for k in range(self.WINDOW - 1, len(h)):
            bars = h[k - self.WINDOW + 1 : k + 1]
            raw[k] = (max(b.high for b in bars), min(b.low for b in bars))
        breaks = set()
        for k in range(self.WINDOW, len(h)):
            hi, lo = raw[k - 1]
            a = self.atr_h1[k - 1]
            if a is not None and (h[k].close < lo - 0.25 * a or h[k].close > hi + 0.25 * a):
                breaks.add(k)
        for k, (hi, lo) in raw.items():
            a, adx = self.atr_h1[k], self.adx[k]
            if a is None or adx is None or adx >= 20:
                continue
            if not 4 * a <= hi - lo <= 10 * a:
                continue
            if any(b in breaks for b in range(k - self.WINDOW + 1, k + 1)):
                continue
            if not self._h1_complete(k - self.WINDOW + 1, k):
                continue
            window = range(k - self.WINDOW + 1, k + 1)
            top = [j for j in window if h[j].high >= hi - self.TOUCH * a]
            bottom = [j for j in window if h[j].low <= lo + self.TOUCH * a]
            if self._clusters(top) >= 2 and self._clusters(bottom) >= 2:
                out[k] = Range(hi, lo, a, k)
        return out

    def _clusters(self, indices: list[int]) -> int:
        count, last = 0, None
        for j in indices:
            if last is None or j - last >= self.CLUSTER_GAP:
                count += 1
            last = j
        return count

    def _h1_complete(self, first: int, last: int) -> bool:
        cal = self.levels.calendar
        for previous, current in zip(self.h1[first:last], self.h1[first + 1 : last + 1],
                                     strict=False):  # fmt: skip
            if cal.open_time("XAUUSD", previous.open_time + H1, current.open_time) > (
                    cal.max_unexplained_gap):  # fmt: skip
                return False
        return True


STRATEGIES = {"A": StrategyA, "C": StrategyC, "B": StrategyB}
