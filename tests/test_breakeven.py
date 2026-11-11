"""EXP-001 break-even replay: activation timing, executable price sides, gaps and the control.

Synthetic day from the engine tests: signal at bar 8, long entry at bar 9's open (bid
2000.00, ask 2000.20, fill 2000.30 after 10 points of entry slippage), stop 1998.50, so
R = 1.70 from the quoted entry and the target is 2003.60. Stop exits slip 30 points.
"""

from datetime import timedelta
from decimal import Decimal as D

from test_backtest_engine import (
    CALENDAR,
    COSTS,
    GBP,
    SIZING,
    XAU,
    Bar,
    StubStrategy,
    flat_bars,
    h1_bars,
    long_setup,
    margin_ok,
    with_bar,
)

from trading.backtest.engine import Backtest, BacktestConfig
from trading.models import Direction
from trading.research.breakeven import VARIANTS, BreakEvenReplay, Mode
from trading.strategies.xauusd_m15_pullback import Setup

CONTROL, BE05, _, _, BE10C = VARIANTS


def engine(bars, signals, trend=Direction.BUY) -> Backtest:
    conversion = [Bar(b.open_time, 1.25, 1.2501, 1.2499, 1.25, 12) for b in bars]
    h1 = h1_bars(bars[0].open_time)
    config = BacktestConfig(D("100"), "GBP", 0, D("50"), SIZING, COSTS)
    return Backtest(m15=bars, h1=h1, conversion_m15=conversion, spec=XAU, conversion_spec=GBP,
                    calendar=CALENDAR, config=config, margin_provider=margin_ok,
                    strategy=StubStrategy(h1, signals, lambda _: trend))  # type: ignore[arg-type]  # fmt: skip


def replay(bars, signals, rule, mode=Mode.BAR_CLOSE, trend=Direction.BUY):
    [trade] = engine(bars, signals, trend).run().trades
    return trade, BreakEvenReplay(engine(bars, signals, trend)).replay(trade, rule, mode)


def edit(bars, index, **values):
    for i in ([index] if isinstance(index, int) else index):
        bars = with_bar(bars, i, **values)
    return bars


# Bar 10 reaches +0.5R on the bid (high 2001.50 >= 2000.30 + 0.85) and also trades below the
# break-even level 2000.30 (low 2000.10): the ambiguous trigger bar.
TRIGGER_BAR = {"high": 2001.5, "low": 2000.1, "open": 2000.4, "close": 2001.0}


def test_control_reproduces_the_version_1_0_trade_exactly():
    for bars in (edit(flat_bars(), 12, high=2004.0, close=2003.0),  # target
                 edit(flat_bars(), 12, low=1998.0)):  # stop  # fmt: skip
        original, result = replay(bars, long_setup(8), CONTROL)
        assert result is not None and result.record == original
        assert result.moved_at is None and not result.break_even_exit


def test_break_even_is_not_applied_inside_the_trigger_bar():
    bars = edit(flat_bars(), 10, **TRIGGER_BAR)
    # Later bars stay above the level, so the stop is never hit after activation.
    bars = edit(bars, range(11, 36), open=2001.0, high=2001.2, low=2000.6, close=2001.0)
    _, result = replay(bars, long_setup(8), BE05)
    assert result is not None
    assert result.moved_at == bars[11].open_time  # active from the next bar's open
    assert result.ambiguous_trigger_bar  # but no exit in bar 10 although it touched 2000.10
    assert result.record.exit_reason == "forced close 16:45 New York"


def test_break_even_exit_after_activation_is_a_stop_with_stop_slippage():
    bars = edit(flat_bars(), 10, **TRIGGER_BAR)
    bars = edit(bars, 11, open=2001.0, high=2001.2, low=2000.2, close=2000.5)
    _, result = replay(bars, long_setup(8), BE05)
    assert result is not None and result.break_even_exit
    assert result.record.exit_reason == "stop (break-even)"
    assert result.record.exit_price == D("2000.00")  # level 2000.30 minus 30 points
    assert result.record.stop == D("1998.50")  # the record keeps the initial stop


def test_gap_through_the_new_stop_at_activation_fills_at_the_open():
    bars = edit(flat_bars(), 10, **TRIGGER_BAR)  # bar 11 opens at 2000.00, below 2000.30
    _, result = replay(bars, long_setup(8), BE05)
    assert result is not None
    assert result.record.exit_reason == "stop (break-even gap)"
    assert result.record.exit_price == D("1999.70")  # open 2000.00 minus 30 points


def test_intrabar_orderings_are_reported_separately_from_the_primary_rule():
    bars = edit(flat_bars(), 10, **TRIGGER_BAR)
    bars = edit(bars, range(11, 36), open=2001.0, high=2001.2, low=2000.6, close=2001.0)
    _, exit_first = replay(bars, long_setup(8), BE05, Mode.INTRABAR_EXIT_FIRST)
    _, no_exit = replay(bars, long_setup(8), BE05, Mode.INTRABAR_NO_EXIT)
    assert exit_first is not None and no_exit is not None
    assert exit_first.record.exit_time == bars[10].open_time  # exits inside the trigger bar
    assert exit_first.record.exit_reason == "stop (break-even)"
    assert no_exit.record.exit_reason == "forced close 16:45 New York"


def test_short_trigger_and_level_use_the_ask():
    # Short: entry at bid 2000.00, fill 1999.90; stop 2001.70, R = 1.70; 0.5R = 0.85. The ask
    # low must reach 1999.05, i.e. a bid low of 1998.85 with the 20-point spread.
    short = {8: Setup(Direction.SELL, 8, D("2001.70"), 2001.5, 1.0)}
    near = edit(flat_bars(), 10, low=1998.9, close=1999.5)  # ask low 1999.10: not reached
    _, result = replay(near, short, BE05, trend=Direction.SELL)
    assert result is not None and result.moved_at is None
    reached = edit(flat_bars(), 10, low=1998.8, close=1999.5)
    _, result = replay(reached, short, BE05, trend=Direction.SELL)
    assert result is not None and result.moved_at == reached[11].open_time
    # Bar 11 opens at bid 2000.00, ask 2000.20 >= level 1999.90: gap exit on the ask.
    assert result.record.exit_reason == "stop (break-even gap)"
    assert result.record.exit_price == D("2000.50")  # ask open 2000.20 plus 30 points


def test_break_even_plus_costs_level_includes_spread_and_both_slippages():
    bars = edit(flat_bars(), 11, high=2002.0)  # trigger at 1.0R = 1.70: bid 2002.00
    bars = edit(bars, range(12, 36), open=2001.5, high=2001.6, low=2000.8, close=2001.0)
    _, result = replay(bars, long_setup(8), BE10C)
    # fill 2000.30 + spread 0.20 + entry slippage 0.10 + stop slippage 0.30
    assert result is not None and result.break_even_level == D("2000.90")
    assert result.record.exit_reason == "stop (break-even)"


def test_break_even_exit_that_later_reaches_the_original_target_is_counted():
    bars = edit(flat_bars(), 10, **TRIGGER_BAR)
    bars = edit(bars, 11, open=2001.0, high=2001.2, low=2000.2, close=2000.5)
    bars = edit(bars, 14, high=2004.0, close=2003.5)
    _, result = replay(bars, long_setup(8), BE05)
    assert result is not None and result.break_even_exit and result.later_reached_target
    assert result.record.exit_time == bars[11].open_time
    assert result.record.exit_time + timedelta(minutes=45) == bars[14].open_time


def _ticks(start, prices, spread="0.20"):
    from trading.research.breakeven import Tick

    step = timedelta(minutes=14, seconds=50) / max(len(prices) - 1, 1)  # spans the bar
    return [Tick(start + i * step, D(p), D(p) + D(spread)) for i, p in enumerate(prices)]


def test_ticks_decide_the_order_inside_the_trigger_bar():
    from trading.research.breakeven import TickOutcome, resolve_from_ticks

    bar = flat_bars()[10]
    args = (Direction.BUY, D("1998.50"), D("2003.60"), D("2001.15"), D("2000.30"))
    # Dip below break-even first, trigger later: no break-even exit in this bar.
    early_dip = _ticks(bar.open_time, ["2000.40", "2000.10", "2001.20", "2001.00", "2000.90"])
    assert resolve_from_ticks(early_dip, bar, *args) == TickOutcome.TRIGGER_ONLY
    # Trigger first, then back to the level: break-even exit inside the bar.
    late_dip = _ticks(bar.open_time, ["2000.40", "2001.20", "2000.80", "2000.30", "2000.90"])
    assert resolve_from_ticks(late_dip, bar, *args) == TickOutcome.BREAK_EVEN


def test_ticks_that_do_not_cover_the_bar_are_not_used():
    from trading.research.breakeven import resolve_from_ticks

    bar = flat_bars()[10]
    partial = _ticks(bar.open_time + timedelta(minutes=5), ["2001.20", "2000.30"])
    assert resolve_from_ticks(partial, bar, Direction.BUY, D("1998.50"), D("2003.60"),
                              D("2001.15"), D("2000.30")) is None  # fmt: skip


def test_short_ticks_are_tested_on_the_ask():
    from trading.research.breakeven import TickOutcome, resolve_from_ticks

    bar = flat_bars()[10]
    # Short fill 1999.90, trigger 1999.05, level 1999.90. Bid 1998.90 means ask 1999.10: no
    # trigger yet; bid 1998.80 (ask 1999.00) triggers; ask back to 1999.90 exits.
    ticks = _ticks(bar.open_time, ["1999.50", "1998.90", "1998.80", "1999.40", "1999.70"])
    assert resolve_from_ticks(ticks, bar, Direction.SELL, D("2001.70"), D("1996.50"),
                              D("1999.05"), D("1999.90")) == TickOutcome.BREAK_EVEN  # fmt: skip
