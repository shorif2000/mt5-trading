"""Generic multi-instrument engine: reconciles with the frozen XAUUSD path on entry, proves the
margin-symbol bug the frozen engine would hit on a real instrument, the FX no-forced-close rule,
the GBPJPY conversion leg for a JPY-quoted instrument, and that GenericLevels/GenericStrategyA
check the calendar under the real symbol rather than "XAUUSD"."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal as D

from candidate_fixtures import NY, h1_from
from test_backtest_engine import GBP, XAU
from test_candidates import CAL, TICK, base, long_breakout_retest

from trading.backtest.bars import Bar
from trading.backtest.engine import BacktestConfig, ExecutionCosts, Outcome
from trading.models import Direction, InstrumentSpec
from trading.research.candidate_engine import CandidateBacktest, CandidateOptions
from trading.research.candidates import StrategyA
from trading.research.multi_market import GenericCandidateBacktest, GenericLevels, GenericStrategyA
from trading.risk.margin import MarginUnavailable, parse_margin_response
from trading.risk.sizing_config import SizingConfig

COSTS = ExecutionCosts(entry_points=D("7"), stop_exit_points=D("40"), market_exit_points=D("7"),
                       sizing_stop_points=D("40"), label="test")  # fmt: skip


def spec(symbol: str, base: str, quote: str, tick: float, digits: int) -> InstrumentSpec:
    return InstrumentSpec(symbol=symbol, base_currency=base, quote_currency=quote,
                          contract_size=100000, tick_size=tick, tick_value=0.8,
                          tick_value_loss=0.8, volume_min=0.01, volume_max=50,
                          volume_step=0.01, trade_allowed=True, digits=digits, point=tick,
                          stops_level_points=0)  # fmt: skip


EURUSD = spec("EURUSD", "EUR", "USD", 0.00001, 5)
GBPJPY = spec("GBPJPY", "GBP", "JPY", 0.001, 3)
USDJPY = spec("USDJPY", "USD", "JPY", 0.001, 3)


def sizing_for(symbol: str) -> SizingConfig:
    return SizingConfig(risk_fraction=D("0.02"), maximum_data_age_seconds=120,
                        tick_value_tolerance=D("0.02"), commission_currency="GBP",
                        commission_per_lot={symbol: D("0")},
                        slippage_points={symbol: None})  # fmt: skip


def margin_echo(symbol: str):  # noqa: ANN201
    def provider(side: str, volume: D, price: D):  # noqa: ANN001, ANN202
        return {"symbol": symbol, "side": side, "volume": float(volume), "price": float(price),
                "margin": 4.0}  # fmt: skip

    return provider


# --- reconciliation with the frozen XAUUSD engine on entry (not exit: force-close is a
# deliberate difference for FX, tested separately below) ------------------------------------


def entry_setup():  # noqa: ANN201
    bars = long_breakout_retest(base())
    h1 = h1_from(bars)
    strategy = StrategyA(bars, h1, CAL, TICK)
    [j] = strategy.signals
    setup = strategy.signals[j].setup
    fill = bars[j + 1]
    return bars, h1, strategy, setup, j, fill


def test_generic_engine_reconciles_with_the_frozen_engine_on_entry_for_xauusd():
    bars, h1, strategy, setup, j, fill = entry_setup()
    config = BacktestConfig(D("1000"), "GBP", 0, D("50"), sizing_for("XAUUSD"), COSTS)
    conversion = [Bar(b.open_time, 1.25, 1.2501, 1.2499, 1.25, 12) for b in bars]

    original = CandidateBacktest(
        candidate=strategy, options=CandidateOptions(), m15=bars, h1=h1, conversion_m15=conversion,
        spec=XAU, conversion_spec=GBP, calendar=CAL, config=config,
        margin_provider=margin_echo("XAUUSD"))  # fmt: skip
    generic = GenericCandidateBacktest(
        candidate=strategy, options=CandidateOptions(), symbol="XAUUSD", conversion_symbol="GBPUSD",
        m15=bars, h1=h1, conversion_m15=conversion, spec=XAU, conversion_spec=GBP, calendar=CAL,
        config=config, margin_provider=margin_echo("XAUUSD"))  # fmt: skip

    orig_record, orig_position = original._try_entry(
        setup, bars[j].open_time + timedelta(minutes=15), fill
    )
    gen_record, gen_position = generic._try_entry(
        setup, bars[j].open_time + timedelta(minutes=15), fill
    )

    assert orig_record.outcome is Outcome.EXECUTABLE
    assert (orig_record.outcome, orig_record.volume, orig_record.estimated_loss,
           orig_record.maximum_risk) == (gen_record.outcome, gen_record.volume,
           gen_record.estimated_loss, gen_record.maximum_risk)  # fmt: skip
    assert orig_position is not None and gen_position is not None
    assert (orig_position.entry_price, orig_position.quoted_entry, orig_position.volume,
           orig_position.target, orig_position.setup.stop) == (
           gen_position.entry_price, gen_position.quoted_entry, gen_position.volume,
           gen_position.target, gen_position.setup.stop)  # fmt: skip


def test_the_frozen_engine_would_reject_a_real_non_gold_margin_response():
    """Proves why GenericCandidateBacktest is needed: the frozen engine always asserts
    symbol="XAUUSD" to parse_margin_response, which real brokers never echo back for another
    instrument (confirmed live against MT5's calc_margin for EURUSD in this session)."""
    real_eurusd_response = {"symbol": "EURUSD", "side": "BUY", "volume": 0.01, "price": 1.10281,
                            "margin": 1.67}  # fmt: skip
    try:
        parse_margin_response(real_eurusd_response, symbol="XAUUSD", side="BUY", volume=D("0.01"))
    except MarginUnavailable as exc:
        assert "different symbol" in str(exc)
    else:
        raise AssertionError("expected MarginUnavailable for a symbol-mismatched response")
    # The fix: tag the request with the real symbol.
    parse_margin_response(real_eurusd_response, symbol="EURUSD", side="BUY", volume=D("0.01"))


# --- FX: no forced close, calendar checked under the real symbol ---------------------------


def test_fx_position_is_not_forced_closed_where_gold_would_be():
    bars = long_breakout_retest(base())
    h1 = h1_from(bars)
    strategy = StrategyA(bars, h1, CAL, TICK)
    [j] = strategy.signals
    config = BacktestConfig(D("1000"), "GBP", 0, D("50"), sizing_for("EURUSD"), COSTS)
    conversion = [Bar(b.open_time, 1.25, 1.2501, 1.2499, 1.25, 12) for b in bars]
    engine = GenericCandidateBacktest(
        candidate=strategy, options=CandidateOptions(), symbol="EURUSD", conversion_symbol="GBPUSD",
        m15=bars, h1=h1, conversion_m15=conversion, spec=EURUSD, conversion_spec=GBP, calendar=CAL,
        config=config, margin_provider=margin_echo("EURUSD"))  # fmt: skip
    far_future = datetime(2026, 11, 16, tzinfo=UTC)
    assert engine._force_close_for(far_future).date() == date(2099, 1, 1)
    # The trading day's 16:45 New York close would have forced out a gold position; confirm
    # the window straddling it is not itself treated as an entry-time problem for FX.
    sixteen_forty = datetime.combine(date(2026, 10, 21), time(16, 30), tzinfo=NY)
    assert engine._entry_time_problem(sixteen_forty) is None


def test_generic_levels_checks_the_real_symbol_not_gold_against_the_calendar():
    bars = long_breakout_retest(base())
    # Gold's daily break (17:00-18:00 New York) is a scheduled closure; forex has none.
    levels_gold = GenericLevels(bars, CAL, "XAUUSD")
    levels_fx = GenericLevels(bars, CAL, "EURUSD")
    start, end = 0, len(bars) - 1
    assert levels_gold.complete(start, end) is True
    assert levels_fx.complete(start, end) is False


def test_generic_strategy_a_matches_the_frozen_strategy_for_xauusd():
    bars = long_breakout_retest(base())
    h1 = h1_from(bars)
    original = StrategyA(bars, h1, CAL, TICK)
    generic = GenericStrategyA(bars, h1, CAL, TICK, "XAUUSD")
    assert original.signals.keys() == generic.signals.keys()
    for j in original.signals:
        assert original.signals[j].setup == generic.signals[j].setup


# --- USDJPY via the GBPJPY conversion leg ---------------------------------------------------


def test_usdjpy_pnl_converts_correctly_through_the_gbpjpy_leg():
    """A long USDJPY trade that hits its target: net JPY P&L converted to GBP via the GBPJPY
    bar (GBP per JPY = 1 / GBPJPY_price), not via a composed GBPUSD x USDJPY cross."""
    start = datetime(2026, 11, 16, 13, 0, tzinfo=UTC)
    bars = [Bar(start + i * timedelta(minutes=15), 150.0, 150.5, 149.5, 150.0, 20)
            for i in range(3)]  # fmt: skip
    bars[1] = Bar(bars[1].open_time, 150.2, 150.3, 150.1, 150.2, 20)  # the entry fill
    bars[2] = Bar(bars[2].open_time, 150.6, 151.0, 150.5, 150.9, 20)  # reaches the target
    gbpjpy = [Bar(b.open_time, 190.0, 190.1, 189.9, 190.0, 15) for b in bars]
    h1 = h1_from(bars)
    strategy = StrategyA(bars, h1, CAL, TICK)
    from trading.research.candidates import CandidateSignal  # noqa: PLC0415
    from trading.strategies.xauusd_m15_pullback import Setup  # noqa: PLC0415

    setup = Setup(Direction.BUY, 0, D("150.00"), 150.0, 1.0, pullback_event_start=0)
    strategy.signals = {0: CandidateSignal(setup, ("buy", 0))}
    config = BacktestConfig(D("1000"), "GBP", 0, D("50"), sizing_for("USDJPY"), COSTS)
    engine = GenericCandidateBacktest(
        candidate=strategy, options=CandidateOptions(), symbol="USDJPY", conversion_symbol="GBPJPY",
        m15=bars, h1=h1, conversion_m15=gbpjpy, spec=USDJPY, conversion_spec=GBPJPY, calendar=CAL,
        config=config, margin_provider=margin_echo("USDJPY"))  # fmt: skip
    record, position = engine._try_entry(setup, bars[0].open_time, bars[1])
    assert record.outcome is Outcome.EXECUTABLE and position is not None
    # entry: bid 150.2, ask 150.22 (20-point spread); target = entry + 2 x (entry - stop).
    assert position.entry_bid == D("150.2") and position.quoted_entry == D("150.220")
    assert position.target == D("150.660")
    hit = engine._exit_level(position, bars[2])
    assert hit == (D("150.660"), "target")
    trade = engine._close(position, bars[2], hit[0], hit[1], bars[2].open_time)
    assert trade is not None and trade.exit_reason == "target"
    gbpjpy_mid = D("190.0075")  # open 190.0 + half the 15-point spread x point 0.001
    rate = 1 / gbpjpy_mid  # GBP per JPY, exactly what _usd_to_gbp_rate computes for this leg
    net_px = D("150.660") - position.entry_price  # no exit slippage on a target fill
    expected_net_gbp = net_px * position.volume * D("100000") * rate
    assert abs(trade.net_gbp - expected_net_gbp) < D("1E-6")
