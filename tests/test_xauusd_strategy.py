"""Version 1.0 signal rules on synthetic XAUUSD bars."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from trading.analysis.indicators import atr_series, ema_series
from trading.backtest.bars import Bar
from trading.models import Direction
from trading.strategies.xauusd_m15_pullback import (
    XauusdM15Pullback,
    round_away,
    target_price,
)

T0 = datetime(2026, 11, 10, 13, 0, tzinfo=UTC)  # first M15 bar; H1 history ends here
TICK = D("0.01")
SIGNAL = 58


def bar(at: datetime, o: float, h: float, lo: float, c: float, spread: int = 20) -> Bar:
    return Bar(at, round(o, 2), round(h, 2), round(lo, 2), round(c, 2), spread)


def h1_series(step: float, count: int = 300) -> list[Bar]:
    """Hourly bars ending just before T0 with a steady trend (step per bar)."""
    bars = []
    for i in range(count):
        close = 2000 + step * i + (0.3 if (step == 0 and i % 2) else 0)
        open_ = close - step / 2
        bars.append(bar(T0 - (count - i) * timedelta(hours=1), open_, max(open_, close) + 0.5,
                        min(open_, close) - 0.5, close))  # fmt: skip
    return bars


def m15_long(*, dip_at: int | None = 55, signal_bullish: bool = True,
             breaks_high: bool = True) -> list[Bar]:  # fmt: skip
    """Rising M15 bars; an optional dip to EMA 20; a confirmation bar at SIGNAL."""
    bars = []
    for i in range(60):
        close = 2000 + 0.2 * i
        o, h, lo = close - 0.1, close + 0.3, close - 0.3
        if i == dip_at:
            lo = close - 5  # pulls back below EMA 20
        if i == SIGNAL:
            previous_high = bars[-1].high
            close = previous_high + (1.0 if breaks_high else -0.05)
            o = close - 0.5 if signal_bullish else close + 0.5
            h, lo = max(o, close) + 0.1, min(o, close) - 0.1
        bars.append(bar(T0 + i * timedelta(minutes=15), o, h, lo, close))
    return bars


def mirrored(bars: list[Bar]) -> list[Bar]:
    pivot = 4000.0
    return [bar(b.open_time, pivot - b.open, pivot - b.low, pivot - b.high, pivot - b.close)
            for b in bars]  # fmt: skip


# --- H1 trend ---------------------------------------------------------------------------


@pytest.mark.parametrize(("step", "expected"), [(1.0, Direction.BUY), (-1.0, Direction.SELL)])
def test_h1_trend_identification(step, expected):
    strategy = XauusdM15Pullback(m15_long(), h1_series(step), TICK)
    assert strategy.trend_at(T0) is expected


def test_conflicting_h1_conditions_mean_no_trend():
    # A long rise then a sharp drop: EMA 50 is still above EMA 200 (not bearish), but the close
    # is below a falling EMA 50 (not bullish).
    rise, drop = h1_series(1.0, count=250), []
    last = rise[-1].close
    for j in range(1, 31):
        close = last - 3 * j
        drop.append(bar(T0 + (j - 1) * timedelta(hours=1), close + 1.5, close + 2, close - 0.5,
                        close))  # fmt: skip
    strategy = XauusdM15Pullback(m15_long(), [*rise, *drop], TICK)
    assert strategy.trend_at(T0 + timedelta(hours=30)) is None


def test_trend_needs_the_warm_up_period():
    strategy = XauusdM15Pullback(m15_long(), h1_series(1.0, count=249), TICK)
    assert strategy.trend_at(T0) is None


def test_trend_uses_only_completed_h1_candles():
    h1 = h1_series(1.0)
    forming = h1[-1]  # closes at T0
    crashed = [*h1[:-1], bar(forming.open_time, forming.open, forming.open, 1000, 1000)]
    before_close = T0 - timedelta(minutes=1)
    assert XauusdM15Pullback(m15_long(), h1, TICK).trend_at(before_close) is Direction.BUY
    assert XauusdM15Pullback(m15_long(), crashed, TICK).trend_at(before_close) is Direction.BUY
    assert XauusdM15Pullback(m15_long(), crashed, TICK).trend_at(T0) is not Direction.BUY


# --- pullback and confirmation ----------------------------------------------------------


def test_valid_long_pullback_and_confirmation():
    m15 = m15_long()
    setup = XauusdM15Pullback(m15, h1_series(1.0), TICK).evaluate(SIGNAL)

    assert setup is not None and setup.direction is Direction.BUY
    atr = atr_series([b.high for b in m15], [b.low for b in m15], [b.close for b in m15], 14)
    extreme = min(b.low for b in m15[55 : SIGNAL + 1])  # from the first touch to the signal
    assert setup.pullback_extreme == extreme
    assert setup.stop == round_away(extreme - 0.2 * atr[SIGNAL], TICK, Direction.BUY)
    assert setup.stop < D(str(extreme))


def test_valid_short_pullback_mirrors_the_long():
    setup = XauusdM15Pullback(mirrored(m15_long()), h1_series(-1.0), TICK).evaluate(SIGNAL)
    assert setup is not None and setup.direction is Direction.SELL
    assert setup.stop > D(str(setup.pullback_extreme))


@pytest.mark.parametrize(
    "bars",
    [
        m15_long(dip_at=None),  # never pulled back towards EMA 20
        m15_long(dip_at=48),  # pullback more than 8 candles before the signal
        m15_long(signal_bullish=False),  # signal candle is bearish
        m15_long(breaks_high=False),  # does not close above the previous high
    ],
    ids=["no-pullback", "stale-pullback", "bearish-candle", "no-break"],
)
def test_invalid_setups_produce_no_signal(bars):
    assert XauusdM15Pullback(bars, h1_series(1.0), TICK).evaluate(SIGNAL) is None


def test_no_long_signal_against_a_bearish_trend():
    assert XauusdM15Pullback(m15_long(), h1_series(-1.0), TICK).evaluate(SIGNAL) is None


def test_signal_does_not_depend_on_later_bars():
    bars = m15_long()
    later = [*bars[: SIGNAL + 1], bar(bars[59].open_time, 1500, 1500, 1400, 1450)]
    first = XauusdM15Pullback(bars, h1_series(1.0), TICK).evaluate(SIGNAL)
    second = XauusdM15Pullback(later, h1_series(1.0), TICK).evaluate(SIGNAL)
    assert first == second


def test_indicator_series_use_only_past_values():
    values = [float(v) for v in range(1, 40)]
    assert ema_series(values, 20)[25] == ema_series(values[:26], 20)[25]
    assert ema_series(values, 20)[18] is None


# --- stop and target --------------------------------------------------------------------


def test_stop_rounds_away_from_the_entry():
    assert round_away(1999.995, TICK, Direction.BUY) == D("1999.99")
    assert round_away(1999.991, TICK, Direction.SELL) == D("2000.00")


@pytest.mark.parametrize(
    ("entry", "stop", "r", "target"),
    [
        ("2000.00", "1998.33", 2.0, "2003.34"),
        ("2000.00", "1998.33", 1.5, "2002.50"),  # 2.505 rounds towards the entry
        ("2000.00", "2001.67", 1.5, "1997.50"),
    ],
)
def test_target_is_r_times_the_stop_distance(entry, stop, r, target):
    assert target_price(D(entry), D(stop), r, TICK) == D(target)
