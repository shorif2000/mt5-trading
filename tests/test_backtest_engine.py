"""Backtest execution assumptions and outcome categories on synthetic bars."""

from bisect import bisect_right
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest

from trading.backtest.bars import Bar
from trading.backtest.engine import Backtest, BacktestConfig, ExecutionCosts, Outcome
from trading.backtest.report import metrics
from trading.market_data.sessions import load_market_calendar
from trading.models import Direction, InstrumentSpec
from trading.risk.sizing_config import SizingConfig
from trading.strategies.xauusd_m15_pullback import PullbackParameters, Setup

CALENDAR = load_market_calendar(Path("config/market_sessions.yaml"))
M15 = timedelta(minutes=15)
# Tuesday 10 Nov 2026 (EST, UTC-5): New York 08:00 is 13:00 UTC.
DAY = datetime(2026, 11, 10, 13, 0, tzinfo=UTC)
XAU = InstrumentSpec(
    symbol="XAUUSD", base_currency="XAU", quote_currency="USD", contract_size=100,
    tick_size=0.01, tick_value=0.8, tick_value_loss=0.8, volume_min=0.01, volume_max=50,
    volume_step=0.01, trade_allowed=True, digits=2, point=0.01, stops_level_points=20,
    freeze_level_points=0, swap_mode=1, swap_long=-5, swap_short=1, swap_rollover3days=3,
)  # fmt: skip
GBP = InstrumentSpec(
    symbol="GBPUSD", base_currency="GBP", quote_currency="USD", contract_size=100000,
    tick_size=0.00001, tick_value=0.8, tick_value_loss=0.8, volume_min=0.01, volume_max=50,
    volume_step=0.01, trade_allowed=True, digits=5, point=0.00001, stops_level_points=0,
)  # fmt: skip
SIZING = SizingConfig(
    risk_fraction=D("0.02"),
    maximum_data_age_seconds=120,
    tick_value_tolerance=D("0.02"),
    commission_currency="GBP",
    commission_per_lot={"XAUUSD": D("0")},
    slippage_points={"XAUUSD": None},  # the backtest sizes with its cost scenario
)
# Synthetic cost scenario: 10 points at entry and on market exits, 30 points on stop exits,
# take profits at the target. Sizing allowance = 10 + 30 = 40 points.
COSTS = ExecutionCosts(
    entry_points=D("10"), stop_exit_points=D("30"), market_exit_points=D("10"),
    sizing_stop_points=D("30"), label="test",
)  # fmt: skip
STOP = D("1998.50")


def flat_bars(start: datetime = DAY, count: int = 36, spread: int = 20) -> list[Bar]:
    return [Bar(start + i * M15, 2000.0, 2000.5, 1999.5, 2000.0, spread) for i in range(count)]


def h1_bars(start: datetime) -> list[Bar]:
    return [Bar(start - timedelta(hours=3) + i * timedelta(hours=1), 2000, 2001, 1999, 2000, 20)
            for i in range(20)]  # fmt: skip


class StubStrategy:
    """Signals at chosen bars; trend from a function of time."""

    def __init__(self, h1: list[Bar], signals: dict[int, Setup],
                 trend: Callable[[datetime], Direction | None]) -> None:  # fmt: skip
        self.params = PullbackParameters()
        self.signals, self._trend = signals, trend
        self.closes = [b.open_time + timedelta(hours=1) for b in h1]

    def evaluate(self, index: int) -> Setup | None:
        return self.signals.get(index)

    def trend_at(self, moment: datetime) -> Direction | None:
        return self._trend(moment)

    def last_completed_h1(self, moment: datetime) -> int | None:
        index = bisect_right(self.closes, moment) - 1
        return index if index >= 0 else None


def margin_ok(side: str, volume: D, price: D) -> dict[str, Any]:
    return {"symbol": "XAUUSD", "side": side, "volume": float(volume), "price": float(price),
            "margin": 4.0}  # fmt: skip


def run(
    bars: list[Bar],
    signals: dict[int, Setup],
    *,
    trend: Callable[[datetime], Any] | None = None,
    margin: Any = margin_ok,
    balance: str = "100",
    sizing: SizingConfig = SIZING,
    costs: ExecutionCosts = COSTS,
):
    conversion = [Bar(b.open_time, 1.25, 1.2501, 1.2499, 1.25, 12) for b in bars]
    h1 = h1_bars(bars[0].open_time)
    strategy = StubStrategy(h1, signals, trend or (lambda _: Direction.BUY))
    config = BacktestConfig(D(balance), "GBP", 0, D("50"), sizing, costs)
    return Backtest(m15=bars, h1=h1, conversion_m15=conversion, spec=XAU, conversion_spec=GBP,
                    calendar=CALENDAR, config=config, margin_provider=margin,
                    strategy=strategy).run()  # type: ignore[arg-type]  # fmt: skip


def long_setup(index: int, stop: D = STOP) -> dict[int, Setup]:
    return {index: Setup(Direction.BUY, index, stop, float(stop) + 0.3, 1.0)}


def with_bar(bars: list[Bar], index: int, **values: float) -> list[Bar]:
    b = bars[index]
    fields = {"open": b.open, "high": b.high, "low": b.low, "close": b.close, **values}
    return [
        *bars[:index],
        Bar(b.open_time, spread_points=b.spread_points, **fields),
        *bars[index + 1 :],
    ]


# Signal at bar 8 (closes New York 10:15); entry at bar 9's open: bid 2000.00, ask 2000.20,
# fill 2000.30 after 10 points of entry slippage. Stop 1998.50; target 2R from the quoted
# entry: 2000.20 + 2 x 1.70 = 2003.60. GBP per USD at GBPUSD mid 1.25006: 0.799961601843.
RATE = D("0.799961601843")


def test_target_exit_books_the_net_result_in_gbp():
    bars = with_bar(flat_bars(), 12, high=2004.0, close=2003.0)
    result = run(bars, long_setup(8))

    [signal] = result.signals
    assert signal.outcome is Outcome.EXECUTABLE and signal.volume == D("0.01")
    [trade] = result.trades
    assert (trade.entry_price, trade.target, trade.exit_reason) == (D("2000.30"), D("2003.60"),
                                                                     "target")  # fmt: skip
    # 3.30 USD on 1 oz (0.01 lot) at the target, no take-profit slippage, no commission.
    assert trade.exit_price == D("2003.60") and trade.net_gbp == D("3.30") * RATE
    assert result.final_balance == D("100") + trade.net_gbp


def test_stop_is_assumed_first_when_both_are_touched():
    bars = with_bar(flat_bars(), 12, high=2004.0, low=1998.0)
    [trade] = run(bars, long_setup(8)).trades
    assert trade.exit_reason == "stop"
    assert trade.exit_price == D("1998.20")  # stop minus 30 points of stop slippage


def test_stop_loss_matches_the_estimated_risk():
    bars = with_bar(flat_bars(), 12, low=1998.0)
    result = run(bars, long_setup(8))
    [signal], [trade] = result.signals, result.trades
    assert signal.estimated_loss is not None and signal.maximum_risk is not None
    assert -trade.net_gbp <= signal.estimated_loss <= signal.maximum_risk


def test_gap_through_the_stop_fills_at_the_open():
    bars = with_bar(flat_bars(), 12, open=1997.0, high=1997.5, low=1996.5, close=1997.0)
    [trade] = run(bars, long_setup(8)).trades
    assert (trade.exit_reason, trade.exit_price) == ("stop (gap)", D("1996.70"))


@pytest.mark.parametrize(
    ("day", "close_utc"),
    [
        (datetime(2026, 11, 10, 13, 0, tzinfo=UTC), datetime(2026, 11, 10, 21, 45, tzinfo=UTC)),
        (datetime(2026, 7, 14, 12, 0, tzinfo=UTC), datetime(2026, 7, 14, 20, 45, tzinfo=UTC)),
    ],
    ids=["winter-EST", "summer-EDT"],
)
def test_position_is_force_closed_at_1645_new_york(day, close_utc):
    result = run(flat_bars(day, count=40), long_setup(8))
    [trade] = result.trades
    assert trade.exit_reason == "forced close 16:45 New York"
    assert trade.exit_time == close_utc


def test_no_entry_within_60_minutes_of_the_daily_break():
    # Signal bar 31 closes at 16:00 New York.
    [signal] = run(flat_bars(), long_setup(31)).signals
    assert (signal.outcome, signal.reasons) == (
        Outcome.FILTERED, ("within 60 minutes of the daily break",),
    )  # fmt: skip


def test_trend_invalidated_on_an_h1_close_exits_at_the_next_open():
    flip = DAY + timedelta(hours=3)  # New York 11:00
    result = run(flat_bars(), long_setup(8), trend=lambda t: Direction.BUY if t < flip else None)
    [trade] = result.trades
    assert trade.exit_reason == "H1 trend invalidated"
    assert trade.exit_time == flip  # the open of the bar after the H1 close


def test_minimum_volume_above_the_limit_is_a_risk_rejection():
    [signal] = run(flat_bars(), long_setup(8, stop=D("1997.20"))).signals
    assert signal.outcome is Outcome.RISK_REJECTED
    assert signal.minimum_volume_loss is not None and signal.minimum_volume_loss > D("2")


def test_stop_wider_than_three_atr_is_filtered():
    setup = {8: Setup(Direction.BUY, 8, D("1996.00"), 1996.3, 1.0)}  # 4.2 USD, ATR 1.0
    [signal] = run(flat_bars(), setup, balance="10000").signals
    assert signal.reasons == ("stop wider than 3 x ATR(14)",)


@pytest.mark.parametrize(
    ("margin", "message"),
    [
        (None, "no margin source"),
        (lambda s, v, p: {"tool_error": "MT5 returned an error"}, "calculation failed"),
        (lambda s, v, p: {**margin_ok(s, v, p), "margin": 150.0}, "exceeds free margin"),
    ],
    ids=["unavailable", "tool-error", "insufficient"],
)
def test_margin_problems_are_margin_rejections(margin, message):
    [signal] = run(flat_bars(), long_setup(8), margin=margin).signals
    assert signal.outcome is Outcome.MARGIN_REJECTED and message in " ".join(signal.reasons)


@pytest.mark.parametrize(("bar_index", "reason"), [(8, "signal spread"), (9, "entry spread")])
def test_spread_above_the_maximum_is_filtered(bar_index, reason):
    bars = flat_bars()
    b = bars[bar_index]
    bars[bar_index] = Bar(b.open_time, b.open, b.high, b.low, b.close, 50)
    [signal] = run(bars, long_setup(8)).signals
    assert signal.outcome is Outcome.FILTERED and signal.reasons[0].startswith(reason)


def test_missing_entry_candle_is_filtered():
    bars = flat_bars()
    del bars[9]
    [signal] = run(bars, long_setup(8)).signals
    assert signal.reasons in (("missing candle before entry",),)


def test_missing_candles_in_the_decision_window_are_filtered():
    bars = flat_bars()
    del bars[4:6]
    [signal] = run(bars, long_setup(6)).signals
    assert signal.reasons == ("missing candles in the decision window",)


def test_unconfirmed_broker_holiday_dates_are_filtered():
    thanksgiving = datetime(2026, 11, 26, 13, 0, tzinfo=UTC)
    [signal] = run(flat_bars(thanksgiving), long_setup(8)).signals
    assert signal.reasons == ("date has an unconfirmed broker holiday schedule",)


def test_only_one_position_at_a_time():
    signals = {**long_setup(8), **long_setup(10)}  # the second fires while the first is open
    result = run(flat_bars(), signals)
    assert len(result.signals) == 1 and len(result.trades) == 1


def test_every_signal_has_exactly_one_outcome():
    signals = {**long_setup(8), **long_setup(31)}
    result = run(with_bar(flat_bars(), 12, high=2004.0), signals)
    assert [s.outcome for s in result.signals] == [Outcome.EXECUTABLE, Outcome.FILTERED]


def test_backtest_refuses_to_run_without_configured_costs():
    unset = SizingConfig(D("0.02"), 120, D("0.02"), "GBP", {"XAUUSD": None}, {"XAUUSD": None})
    with pytest.raises(ValueError, match="commission must be configured"):
        run(flat_bars(), long_setup(8), sizing=unset)


# --- revised cost model -----------------------------------------------------------------


def short_setup(index: int, stop: D = D("2001.50")) -> dict[int, Setup]:
    return {index: Setup(Direction.SELL, index, stop, float(stop) - 0.3, 1.0)}


def with_spread(bars: list[Bar], index: int, spread: int) -> list[Bar]:
    b = bars[index]
    return [*bars[:index], Bar(b.open_time, b.open, b.high, b.low, b.close, spread),
            *bars[index + 1:]]  # fmt: skip


def test_long_stop_loss_execution():
    result = run(with_bar(flat_bars(), 12, low=1998.0), long_setup(8))
    [trade], [signal] = result.trades, result.signals
    # Buy filled at 2000.30, stop filled at 1998.20: 2.10 USD on 1 oz.
    assert (trade.exit_kind, trade.exit_price) == ("stop", D("1998.20"))
    assert trade.net_gbp == D("-2.10") * RATE
    # Sizing allowed 170 ticks of distance + 40 points of slippage = 210 ticks: exactly the loss.
    assert -trade.net_gbp == signal.estimated_loss
    assert signal.estimated_loss is not None and signal.estimated_loss <= D("2")


def test_short_stop_loss_execution_pays_the_exit_bar_spread():
    # Sell at bid 2000.00 (fill 1999.90). The stop triggers on the ask; the exit bar has a
    # 40-point spread, so ask high = 2001.60 >= 2001.50.
    bars = with_spread(with_bar(flat_bars(), 12, high=2001.2), 12, 40)
    result = run(bars, short_setup(8), trend=lambda _: Direction.SELL)
    [trade], [signal] = result.trades, result.signals
    assert (trade.exit_kind, trade.exit_price) == ("stop", D("2001.80"))  # stop + 30 points
    assert trade.spread_cost_gbp == D("0.40") * RATE  # the exit bar's spread, not the entry's
    # Bid-to-bid: 2000.00 sold, ask 2001.50 = bid 2001.10 bought back: -1.10.
    assert trade.gross_gbp == D("-1.10") * RATE
    assert trade.net_gbp == D("-1.90") * RATE == -signal.estimated_loss  # type: ignore[operator]


def test_long_spread_cost_is_the_entry_bar_spread():
    bars = with_spread(with_bar(flat_bars(), 12, high=2004.0), 9, 30)  # entry bar spread 30
    bars = with_spread(bars, 12, 60)  # wide exit bar spread does not affect a long's cost
    [trade] = run(bars, long_setup(8)).trades
    assert trade.spread_cost_gbp == D("0.30") * RATE


def test_entry_and_stop_slippage_apply_independently():
    bars = with_bar(flat_bars(), 12, low=1998.0)
    entry_only = ExecutionCosts(D("25"), D("0"), D("25"), sizing_stop_points=D("0"))
    stop_only = ExecutionCosts(D("0"), D("25"), D("0"), sizing_stop_points=D("25"))
    [a] = run(bars, long_setup(8), costs=entry_only).trades
    [b] = run(bars, long_setup(8), costs=stop_only).trades
    assert (a.entry_slippage_gbp, a.exit_slippage_gbp) == (D("0.25") * RATE, D(0))
    assert (b.entry_slippage_gbp, b.exit_slippage_gbp) == (D(0), D("0.25") * RATE)
    assert (a.entry_price, a.exit_price) == (D("2000.45"), D("1998.50"))
    assert (b.entry_price, b.exit_price) == (D("2000.20"), D("1998.25"))


@pytest.mark.parametrize("direction", ["long", "short"])
def test_take_profit_fills_at_the_target_without_slippage(direction):
    if direction == "long":
        bars, setups = with_bar(flat_bars(), 12, high=2004.0), long_setup(8)
    else:  # short target 2000.00 - 2 x 1.50 = 1997.00, on the ask
        bars, setups = with_bar(flat_bars(), 12, low=1996.5), short_setup(8)
    trend = Direction.BUY if direction == "long" else Direction.SELL
    [trade] = run(bars, setups, trend=lambda _: trend).trades
    assert trade.exit_kind == "target" and trade.exit_price == trade.target
    assert trade.exit_slippage_gbp == 0


def test_market_exits_use_the_entry_slippage_scenario():
    [trade] = run(flat_bars(count=40), long_setup(8)).trades  # forced close at 16:45
    assert trade.exit_kind == "market" and trade.exit_slippage_gbp == D("0.10") * RATE


def test_costs_reconcile_for_every_trade_and_in_total():
    setups = {**long_setup(8), **short_setup(20)}
    bars = with_spread(with_bar(with_bar(flat_bars(), 12, high=2004.0), 22, high=2001.6), 22, 35)
    switch = DAY + timedelta(hours=4)  # long trend first, short trend later
    result = run(bars, setups, trend=lambda t: Direction.BUY if t < switch else Direction.SELL)
    assert len(result.trades) == 2
    for t in result.trades:
        costs = t.spread_cost_gbp + t.entry_slippage_gbp + t.exit_slippage_gbp + t.commission_gbp
        assert t.gross_gbp - costs == t.net_gbp
    assert metrics(result).costs_reconcile


def test_actual_reward_to_risk_after_entry_slippage():
    [trade] = run(with_bar(flat_bars(), 12, high=2004.0), long_setup(8)).trades
    # The target is 2R from the quoted 2000.20; from the 2000.30 fill it is 3.30 / 1.80.
    assert trade.planned_reward_to_risk == D("3.30") / D("1.80")
    assert trade.realised_r == trade.net_gbp / trade.estimated_loss  # type: ignore[operator]
    assert trade.realised_r is not None and trade.realised_r < 2


def test_two_percent_limit_holds_under_the_revised_costs():
    # A stop sized close to the limit at GBP 100: realised loss never exceeds 2% (no gap).
    result = run(with_bar(flat_bars(), 12, low=1997.0), long_setup(8, stop=D("1997.90")))
    [signal] = result.signals
    if signal.outcome is Outcome.EXECUTABLE:
        [trade] = result.trades
        assert -trade.net_gbp <= signal.estimated_loss <= D("2")  # type: ignore[operator]
    else:
        assert signal.outcome is Outcome.RISK_REJECTED


def test_sizing_allowance_covers_the_simulated_slippage():
    costs = ExecutionCosts(D("7"), D("40"), D("7"), sizing_stop_points=D("60"))
    assert costs.sizing_allowance() == D("67")  # entry + p95 stop, not the simulated p90
    assert ExecutionCosts(D("5"), D("10"), D("50")).sizing_allowance() == D("55")
    with pytest.raises(ValueError, match="must cover the simulated stop slippage"):
        ExecutionCosts(D("7"), D("60"), D("7"), sizing_stop_points=D("40"))


def test_distinct_pullback_events_are_counted_once():
    # Two qualifying candles (bars 8 and 9) from the same pullback, which started at bar 7.
    same = {i: Setup(Direction.BUY, i, D("1990.00"), 1990.3, 1.0, pullback_event_start=7)
            for i in (8, 9)}  # fmt: skip
    m = metrics(run(flat_bars(), same, balance="10000"))
    assert (m.signals, m.distinct_pullback_events) == (2, 1)
