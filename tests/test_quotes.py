"""Quote observations around a modelled entry: executable side, offsets, coverage, model gap."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from trading.models import Direction
from trading.research.breakeven import Tick
from trading.research.quotes import observe

T = datetime(2026, 3, 17, 14, 30, tzinfo=UTC)
POINT = D("0.01")


def tick(seconds: float, bid: str, ask: str) -> Tick:
    return Tick(T + timedelta(seconds=seconds), D(bid), D(ask))


TICKS = [tick(-2, "2000.00", "2000.20"),  # before the entry moment
         tick(0.1, "2000.05", "2000.25"),  # first quote: ask 2000.25, bid 2000.05
         tick(0.8, "2000.10", "2000.35"),
         tick(3.0, "1999.90", "2000.12")]  # fmt: skip
END = T + timedelta(seconds=301)


def test_buy_uses_the_ask_and_reports_movement_against_the_first_quote():
    o = observe(TICKS, T, Direction.BUY, D("2000.00"), 20, POINT, window_end=END)
    assert o is not None
    assert o.first_executable == D("2000.25") and o.first_spread_points == D("20")
    assert o.adverse_points[0.5] == D("0")  # still the first quote at +0.5 s
    assert o.adverse_points[1.0] == D("10")  # ask 2000.35: 10 points worse for a buy
    assert o.adverse_points[5.0] == D("-13")  # ask 2000.12: better
    assert o.max_adverse_points_5s == D("10")
    # Model entry = bar open 2000.00 + 20-point spread = 2000.20: 5 points better than real.
    assert o.model_executable == D("2000.20") and o.model_minus_first_points == D("-5")
    assert (o.pre_entry_bid, o.pre_entry_ask) == (D("2000.00"), D("2000.20"))


def test_sell_uses_the_bid_and_a_lower_bid_is_adverse():
    o = observe(TICKS, T, Direction.SELL, D("2000.00"), 20, POINT, window_end=END)
    assert o is not None and o.first_executable == D("2000.05")
    assert o.adverse_points[1.0] == D("-5")  # bid 2000.10: better for a sell
    assert o.adverse_points[5.0] == D("15")  # bid 1999.90: 15 points worse
    assert o.model_minus_first_points == D("5")  # model bid 2000.00 vs real 2000.05


def test_offsets_beyond_the_fetched_window_are_not_filled():
    o = observe(TICKS, T, Direction.BUY, D("2000.00"), 20, POINT,
                window_end=T + timedelta(seconds=10))  # fmt: skip
    assert o is not None and o.adverse_points[5.0] is not None
    assert o.adverse_points[15.0] is None and o.spread_points[300.0] is None


def test_no_quote_soon_after_the_entry_moment_gives_no_observation():
    late = [tick(-5, "2000.0", "2000.2"), tick(90, "2000.1", "2000.3")]
    assert observe(late, T, Direction.BUY, D("2000"), 20, POINT, window_end=END) is None
