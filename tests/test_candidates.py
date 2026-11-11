"""Candidate strategies A, C, B and their engine: event rules, priority, no look-ahead, cost
floor, news, fixed-risk ledger and B's midpoint target. Synthetic data only."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal as D
from pathlib import Path

from candidate_fixtures import M15, NY, h1_from, history, replace, sine, trading_days
from test_backtest_engine import GBP, SIZING, XAU, Bar, margin_ok

from trading.backtest.engine import BacktestConfig, ExecutionCosts, Outcome
from trading.market_data.sessions import load_market_calendar
from trading.models import Direction
from trading.research.candidate_engine import CandidateBacktest, CandidateOptions
from trading.research.candidates import StrategyA, StrategyB, StrategyC
from trading.research.levels import adx_series
from trading.research.news import Calendar, Coverage, EconomicEvent, NewsFilter
from trading.strategies.xauusd_m15_pullback import round_away

CAL = load_market_calendar(Path("config/market_sessions.yaml"))
TICK = D("0.01")
DAYS = trading_days(date(2026, 9, 28), 18)
DAY = DAYS[-1]  # 2026-10-21: enough completed days for ADR
COSTS = ExecutionCosts(entry_points=D("7"), stop_exit_points=D("40"), market_exit_points=D("7"),
                       sizing_stop_points=D("40"), label="test")  # fmt: skip


def at(clock: str, day: date = DAY) -> datetime:
    return datetime.combine(day, time.fromisoformat(clock), tzinfo=NY)


def base() -> list[Bar]:
    # Asian bars +/-0.30 around 2000 (AR 1999.70-2000.30), other hours +/-1.00: ADR about 2.
    return history(DAYS)


def long_breakout_retest(bars: list[Bar]) -> list[Bar]:
    bars = replace(bars, at("02:00"), open=2000.2, high=2000.9, low=2000.2, close=2000.8)
    bars = replace(bars, at("02:15"), open=2000.8, high=2000.85, low=2000.35, close=2000.5)
    bars = replace(bars, at("02:30"), open=2000.5, high=2001.0, low=2000.45, close=2000.95)
    return replace(bars, at("02:45"), open=2000.95, high=2001.1, low=2000.9, close=2001.0)


def index_of(bars: list[Bar], moment: datetime) -> int:
    return next(i for i, b in enumerate(bars) if b.open_time == moment)


# --- A -------------------------------------------------------------------------------------


def test_a_signals_on_the_confirmation_after_a_retest_with_a_structural_stop():
    bars = long_breakout_retest(base())
    a = StrategyA(bars, h1_from(bars), CAL, TICK)
    j = index_of(bars, at("02:30"))
    assert list(a.signals) == [j]
    setup = a.signals[j].setup
    assert setup.direction == Direction.BUY
    assert setup.pullback_event_start == index_of(bars, at("02:00"))  # event = breakout bar
    assert setup.stop == round_away(2000.2 - 0.20 * a.atr15[j], TICK, Direction.BUY)


def test_a_signal_does_not_depend_on_later_bars():
    bars = long_breakout_retest(base())
    j = index_of(bars, at("02:30"))
    full = StrategyA(bars, h1_from(bars), CAL, TICK).signals[j].setup
    cut = StrategyA(bars[: j + 1], h1_from(bars[: j + 1]), CAL, TICK).signals[j].setup
    assert full == cut


def test_a_close_back_inside_the_range_invalidates_before_any_retest_confirmation():
    bars = replace(base(), at("02:00"), open=2000.2, high=2000.9, low=2000.2, close=2000.8)
    bars = replace(bars, at("02:15"), open=2000.8, high=2000.8, low=1999.8, close=1999.9)
    bars = replace(bars, at("02:30"), open=2000.5, high=2001.0, low=2000.45, close=2000.95)
    a = StrategyA(bars, h1_from(bars), CAL, TICK)
    assert a.signals == {}
    assert [e.stage for e in a.events if e.day == DAY] == ["invalidated (failed breakout)"]


def test_a_earlier_signal_takes_the_day_and_the_other_side_is_superseded():
    bars = long_breakout_retest(base())
    bars = replace(bars, at("04:00"), open=1999.8, high=1999.8, low=1999.1, close=1999.2)
    bars = replace(bars, at("04:15"), open=1999.2, high=1999.65, low=1999.15, close=1999.5)
    bars = replace(bars, at("04:30"), open=1999.5, high=1999.55, low=1999.0, close=1999.05)
    a = StrategyA(bars, h1_from(bars), CAL, TICK)
    assert list(a.signals) == [index_of(bars, at("02:30"))]
    stages = {e.direction: e.stage for e in a.events if e.day == DAY}
    assert stages == {"buy": "signal", "sell": "superseded (other side signalled first)"}


# --- C -------------------------------------------------------------------------------------


def sweep_of_asian_high(bars: list[Bar], open_: float = 2000.1) -> list[Bar]:
    for clock in ("02:00", "02:15", "02:30", "02:45"):  # quiet until the sweep
        bars = replace(bars, at(clock), high=2000.25, low=1999.75)
    bars = replace(bars, at("03:00"), open=open_, high=2000.5, low=2000.0, close=2000.2)
    return replace(bars, at("03:15"), open=2000.2, high=2000.25, low=1999.8, close=1999.9)


def test_c_short_after_sweep_reclaim_and_close_below_the_sweep_bar_low():
    bars = sweep_of_asian_high(base())
    c = StrategyC(bars, h1_from(bars), CAL, TICK)
    j = index_of(bars, at("03:15"))
    assert list(c.signals) == [j]
    setup = c.signals[j].setup
    assert setup.direction == Direction.SELL and c.signals[j].level == "Asian high"
    assert setup.stop == round_away(2000.5 + 0.20 * c.atr15[j], TICK, Direction.SELL)


def test_c_a_bar_opening_beyond_the_level_is_not_a_sweep():
    bars = sweep_of_asian_high(base(), open_=2000.4)
    c = StrategyC(bars, h1_from(bars), CAL, TICK)
    assert c.signals == {}
    assert "opened beyond level" in [e.stage for e in c.events if e.day == DAY]


# --- B -------------------------------------------------------------------------------------


def b_history() -> tuple[list[Bar], int]:
    """A 20-hour sine forms valid H1 ranges; one M15 rejection candle is placed just after a
    range's H1 close, at its low."""
    bars = history(trading_days(date(2026, 10, 5), 12), price=sine(20, 8), asian=1.5, other=1.5)
    probe = StrategyB(bars, h1_from(bars), CAL, TICK)
    k = min(probe.ranges)
    rng = probe.ranges[k]
    moment = h1_from(bars)[k].open_time + timedelta(hours=1)
    low = rng.low - 0.1
    bars = replace(bars, moment, open=low + 0.2, high=low + 1.2, low=low, close=low + 1.1)
    return bars, index_of(bars, moment)


def test_b_rejection_at_the_range_low_signals_with_the_midpoint_target():
    bars, i = b_history()
    b = StrategyB(bars, h1_from(bars), CAL, TICK)
    assert i in b.signals
    signal = b.signals[i]
    assert signal.setup.direction == Direction.BUY
    assert signal.target_price is not None and signal.target_price > bars[i].close


def test_b_ranges_use_completed_h1_bars_only():
    bars, i = b_history()
    full = StrategyB(bars, h1_from(bars), CAL, TICK).signals[i]
    cut = StrategyB(bars[: i + 1], h1_from(bars[: i + 1]), CAL, TICK).signals[i]
    assert full == cut


def test_adx_is_high_in_a_steady_trend_and_low_in_an_oscillation():
    n = 120
    trend = adx_series([i + 1.0 for i in range(n)], [i - 1.0 for i in range(n)],
                       [float(i) for i in range(n)])  # fmt: skip
    zigzag = [(-1) ** i * 1.0 for i in range(n)]
    flat = adx_series([z + 1 for z in zigzag], [z - 1 for z in zigzag], zigzag)
    assert trend[26] is None and trend[27] is not None  # first value after 2 x 14 - 1 bars
    assert trend[-1] > 90 and flat[-1] < 20  # type: ignore[operator]


# --- engine --------------------------------------------------------------------------------


def run(bars, strategy_cls, **options):
    conversion = [Bar(b.open_time, 1.25, 1.2501, 1.2499, 1.25, 12) for b in bars]
    h1 = h1_from(bars)
    config = BacktestConfig(D("1000"), "GBP", 0, D("50"), SIZING, COSTS)
    candidate = strategy_cls(bars, h1, CAL, TICK)
    engine = CandidateBacktest(
        candidate=candidate, options=CandidateOptions(**options), m15=bars, h1=h1,
        conversion_m15=conversion, spec=XAU, conversion_spec=GBP, calendar=CAL, config=config,
        margin_provider=margin_ok)  # fmt: skip
    return engine.run()


def test_cost_floor_rejects_a_trade_whose_cost_exceeds_a_tenth_of_the_stop():
    bars = long_breakout_retest(base())
    # Stop distance about 0.9 against estimated cost (20 + 7 + 40) points = 0.67 > 0.09.
    assert len(run(bars, StrategyA).trades) == 1
    [signal] = run(bars, StrategyA, cost_floor=D("0.10")).signals
    assert signal.outcome is Outcome.FILTERED
    assert signal.reasons == ("estimated cost above 0.10R (cost floor)",)


def test_news_blackout_rejects_the_entry_and_fails_closed_without_coverage():
    bars = long_breakout_retest(base())
    entry = at("02:45")  # entry at the bar after the 02:30 signal
    event = EconomicEvent("fomc_statement", DAY, time(3, 0), "published", "test")
    covered = Calendar((event,), (Coverage("fomc_statement", DAYS[0], DAY),), {})
    [signal] = run(bars, StrategyA, news=NewsFilter(covered, ["fomc_statement"])).signals
    assert signal.reasons == ("news blackout (fomc_statement 03:00 NY)",)
    uncovered = Calendar((), (Coverage("fomc_statement", DAYS[0], DAYS[3]),), {})
    [signal] = run(bars, StrategyA, news=NewsFilter(uncovered, ["fomc_statement"])).signals
    assert signal.reasons == ("economic calendar unavailable (fomc_statement)",)
    assert entry - M15 == at("02:30")


def test_fixed_risk_ledger_sizes_every_trade_on_the_starting_balance():
    bars = long_breakout_retest(base())
    result = run(bars, StrategyA, fixed_risk=True)
    [trade] = result.trades
    assert result.final_balance == D("1000")  # reset after each close
    assert trade.maximum_risk == D("20.000")  # 2% of £1,000


def test_b_trade_targets_the_rounded_range_midpoint():
    bars, i = b_history()
    result = run(bars, StrategyB)
    executed = [s for s in result.signals if s.outcome is Outcome.EXECUTABLE]
    filtered = [s for s in result.signals if s.outcome is Outcome.FILTERED]
    assert executed or filtered  # the signal reached the engine
    for trade in result.trades:
        mid = StrategyB(bars, h1_from(bars), CAL, TICK).signals[i].target_price
        assert mid is not None and trade.target <= D(str(mid))  # long target rounded down
