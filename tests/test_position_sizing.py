"""Business rules for sizing one trade at no more than 2 % of the current account balance.

All account and instrument data is synthetic. Tick values are built from contract size, tick
size and the snapshot's own quotes, as MT5 would report them in the account currency.
"""

import dataclasses
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from trading.models import (
    AccountSnapshot,
    Direction,
    InstrumentSpec,
    MarketSnapshot,
    PendingOrder,
    Position,
    Quote,
)
from trading.risk.position_sizing import SizingRequest, check_volume, size_position
from trading.risk.sizing_config import SizingConfig, load_sizing_config, parse_sizing_config

NOW = datetime(2026, 11, 10, 10, 0, tzinfo=UTC)
# symbol: (bid, ask, tick size, contract size, base, profit currency)
MARKET = {
    "EURUSD": (1.10000, 1.10010, 0.00001, 100000, "EUR", "USD"),
    "GBPUSD": (1.25000, 1.25012, 0.00001, 100000, "GBP", "USD"),
    "USDJPY": (150.000, 150.012, 0.001, 100000, "USD", "JPY"),
    "XAUUSD": (2000.00, 2000.20, 0.01, 100, "XAU", "USD"),
}


def rate(source: str, target: str) -> float:
    """Mid-price conversion used to build consistent synthetic tick values."""
    mids = {(b, q): (bid + ask) / 2 for bid, ask, _, _, b, q in MARKET.values()}
    if source == target:
        return 1.0
    for (b, q), mid in mids.items():
        if (b, q) == (source, target):
            return mid
        if (q, b) == (source, target):
            return 1 / mid
    return rate(source, "USD") * rate("USD", target)


def snapshot(
    currency: str = "USD", balance: float = 10_000.0, age: timedelta = timedelta(seconds=5),
    **spec_overrides: Any,
) -> MarketSnapshot:  # fmt: skip
    taken = NOW - age
    quotes, specs = [], []
    for symbol, (bid, ask, tick, size, base, profit) in MARKET.items():
        digits = -int(D(str(tick)).as_tuple().exponent)
        quotes.append(Quote(symbol=symbol, bid=bid, ask=ask, timestamp=taken, point=tick,
                            digits=digits))  # fmt: skip
        tick_value = size * tick * rate(profit, currency) if currency in {"USD", "GBP"} else 1.0
        fields: dict[str, Any] = {
            "symbol": symbol, "base_currency": base, "quote_currency": profit,
            "contract_size": size, "tick_size": tick, "tick_value": tick_value,
            "tick_value_profit": tick_value, "tick_value_loss": tick_value,
            "volume_min": 0.01, "volume_max": 50.0, "volume_step": 0.01, "trade_allowed": True,
            "digits": digits, "point": tick, "stops_level_points": 10, "freeze_level_points": 0,
            "swap_mode": 1, "swap_long": -6.0, "swap_short": 2.0, "swap_rollover3days": 3,
        }  # fmt: skip
        fields.update(spec_overrides.get(symbol, {}))
        specs.append(InstrumentSpec(**fields))
    account = AccountSnapshot(
        login="REDACTED", server="Example-Demo", currency=currency, balance=balance, credit=0,
        equity=balance * 3, margin=0, free_margin=balance * 3, timestamp=taken,
    )  # fmt: skip
    return MarketSnapshot(account=account, quotes=quotes, instruments=specs, generated_at=taken)


def config(currency: str = "USD", **overrides: Any) -> SizingConfig:
    values: dict[str, Any] = {
        "risk_fraction": D("0.02"),
        "maximum_data_age_seconds": 120,
        "tick_value_tolerance": D("0.02"),
        "commission_currency": currency,
        "commission_per_lot": {s: D("7") for s in MARKET},
        "slippage_points": {s: D("10") for s in MARKET},
    }
    values.update(overrides)
    return SizingConfig(**values)


def buy_eurusd(**overrides: Any) -> SizingRequest:
    # Entry at the ask; stop 500 points (50 pips) below.
    values: dict[str, Any] = {"symbol": "EURUSD", "direction": "buy", "entry": D("1.10010"),
                              "stop_loss": D("1.09510"), "entry_basis": "executable",
                              "holding_nights": 0}  # fmt: skip
    values.update(overrides)
    return SizingRequest(**values)


def rejection(result: Any) -> str:
    assert not result.accepted and result.volume is None
    return " | ".join(result.reasons)


# --- the 2 % rule -----------------------------------------------------------------------


def test_normal_trade_is_sized_within_two_percent_of_balance():
    result = size_position(snapshot(), buy_eurusd(), config(), now=NOW)

    # 10,000 USD balance -> 200 USD limit. Per lot: 500 points + 10 slippage = 510 ticks
    # x 1 USD + 7 USD commission = 517 USD. 200 / 517 = 0.386 -> 0.38 lots.
    assert result.accepted
    assert result.maximum_risk == D("200.00")
    assert result.volume == D("0.38")
    assert result.estimated_loss == D("196.46")
    assert result.estimated_loss <= result.maximum_risk


def test_volume_that_would_exceed_the_limit_is_rejected():
    sized = size_position(snapshot(), buy_eurusd(), config(), now=NOW)
    spec = snapshot().instruments[0]
    assert sized.loss_model is not None and sized.maximum_risk is not None

    one_step_more = check_volume(D("0.39"), sized.loss_model, sized.maximum_risk, spec, "USD")
    assert "estimated loss 201.63 USD exceeds the 200.00 USD limit" in rejection(one_step_more)


def test_volume_rounds_down_to_the_broker_step_never_up():
    coarse = snapshot(EURUSD={"volume_step": 0.1, "volume_min": 0.1})
    result = size_position(coarse, buy_eurusd(), config(), now=NOW)
    assert result.volume == D("0.3")  # 0.386 lots rounds down, not to 0.4 (206.80 USD)
    assert result.estimated_loss == D("155.10")


def test_volume_is_capped_at_the_broker_maximum():
    result = size_position(snapshot(balance=10_000_000), buy_eurusd(), config(), now=NOW)
    assert result.accepted and result.volume == D("50.00")


def test_minimum_volume_above_the_limit_is_rejected():
    result = size_position(snapshot(balance=100), buy_eurusd(), config(), now=NOW)
    # 2 USD limit; the 0.01 lot minimum would lose 5.17 USD.
    assert "minimum volume 0.01 would lose 5.17 USD, above the 2.00 USD limit" in rejection(result)
    assert result.estimated_loss == D("5.1700")


def test_limit_follows_the_current_balance():
    larger = size_position(snapshot(balance=10_000), buy_eurusd(), config(), now=NOW)
    smaller = size_position(snapshot(balance=5_000), buy_eurusd(), config(), now=NOW)
    assert (larger.maximum_risk, larger.volume) == (D("200.00"), D("0.38"))
    assert (smaller.maximum_risk, smaller.volume) == (D("100.00"), D("0.19"))


def test_limit_uses_balance_not_equity_or_free_margin():
    result = size_position(snapshot(balance=10_000), buy_eurusd(), config(), now=NOW)
    # The synthetic equity and free margin are three times the balance; they are ignored.
    assert result.maximum_risk == D("200.00")


@pytest.mark.parametrize("balance", [0.0, -50.0])
def test_non_positive_balance_is_rejected(balance):
    assert "is not positive" in rejection(
        size_position(snapshot(balance=balance), buy_eurusd(), config(), now=NOW)
    )


# --- loss tick value --------------------------------------------------------------------


def test_missing_loss_tick_value_is_rejected_without_falling_back():
    data = snapshot(EURUSD={"tick_value_loss": None})  # generic tick_value is still present
    assert "missing tick_value_loss" in rejection(
        size_position(data, buy_eurusd(), config(), now=NOW)
    )


def test_loss_tick_value_inconsistent_with_contract_and_quotes_is_rejected():
    data = snapshot(EURUSD={"tick_value_loss": 2.0})  # 1 USD expected
    assert "conversion is unreliable" in rejection(
        size_position(data, buy_eurusd(), config(), now=NOW)
    )


@pytest.mark.parametrize("value", [0.0, -1.0])
def test_zero_or_negative_loss_tick_value_is_invalid(value):
    with pytest.raises(ValidationError, match="tick_value_loss"):
        snapshot(EURUSD={"tick_value_loss": value})


def test_loss_tick_value_is_used_rather_than_profit_tick_value():
    # A losing tick is worth slightly more than a winning one; the loss value must be used.
    data = snapshot(EURUSD={"tick_value_loss": 1.01, "tick_value": 0.99})
    result = size_position(data, buy_eurusd(), config(), now=NOW)
    assert result.loss_model is not None and result.loss_model.tick_value_loss == D("1.01")


# --- account currency and conversion ----------------------------------------------------


def test_gbp_account_uses_gbp_tick_values_and_limit():
    result = size_position(snapshot("GBP"), buy_eurusd(), config("GBP"), now=NOW)
    assert result.accepted and result.account_currency == "GBP"
    assert result.maximum_risk == D("200.00")  # 2 % of 10,000 GBP
    # 1 USD per tick converted at GBPUSD 1.25006 is about 0.79996 GBP.
    assert result.loss_model is not None
    assert abs(result.loss_model.tick_value_loss - D("0.79996")) < D("0.00001")
    assert result.volume == D("0.48")


def test_cross_currency_conversion_through_usd_is_verified():
    # USDJPY in a GBP account: JPY -> USD -> GBP from the USDJPY and GBPUSD quotes.
    request = SizingRequest("USDJPY", "sell", D("150.000"), D("150.500"), "executable", 0)
    assert size_position(snapshot("GBP"), request, config("GBP"), now=NOW).accepted


def test_account_currency_without_conversion_quotes_is_rejected():
    result = size_position(snapshot("CHF"), buy_eurusd(), config("CHF"), now=NOW)
    assert "no quotes to convert USD to CHF" in rejection(result)


def test_commission_in_another_currency_is_rejected():
    result = size_position(snapshot("GBP"), buy_eurusd(), config("USD"), now=NOW)
    assert "commission is configured in USD, not the account currency GBP" in rejection(result)


# --- spread, slippage and commission ----------------------------------------------------


def loss_per_lot(**request: Any) -> D:
    result = size_position(snapshot(), buy_eurusd(**request), config(), now=NOW)
    assert result.loss_model is not None
    return result.loss_model.loss_per_lot


def test_spread_is_added_to_a_buy_priced_from_the_bid():
    # Same 500-point distance, but a bid-based buy fills 10 points higher at the ask.
    executable = loss_per_lot()
    from_bid = loss_per_lot(entry=D("1.10000"), stop_loss=D("1.09500"), entry_basis="bid")
    assert from_bid - executable == D("10")


def test_spread_is_not_added_to_a_sell():
    sell = dict(direction="sell", entry=D("1.10000"), stop_loss=D("1.10500"))
    assert loss_per_lot(**sell, entry_basis="bid") == loss_per_lot(**sell, entry_basis="executable")


def test_slippage_and_commission_increase_the_loss_per_lot():
    base = size_position(snapshot(), buy_eurusd(), config(), now=NOW)
    no_costs = size_position(
        snapshot(), buy_eurusd(),
        config(commission_per_lot={"EURUSD": D("0")}, slippage_points={"EURUSD": D("0")}),
        now=NOW,
    )  # fmt: skip
    assert base.loss_model is not None and no_costs.loss_model is not None
    assert base.loss_model.loss_per_lot - no_costs.loss_model.loss_per_lot == D("17")
    assert no_costs.volume == D("0.40") and base.volume == D("0.38")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"commission_per_lot": {"EURUSD": None}}, "commission per lot is not configured"),
        ({"slippage_points": {"EURUSD": None}}, "slippage assumption is not configured"),
        ({"commission_per_lot": {}}, "commission per lot is not configured"),
    ],
)
def test_unknown_costs_are_rejected_not_assumed_zero(overrides, message):
    assert message in rejection(
        size_position(snapshot(), buy_eurusd(), config(**overrides), now=NOW)
    )


# --- stop loss and prices ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("request_overrides", "message"),
    [
        ({"stop_loss": None}, "stop loss is missing"),
        ({"stop_loss": D("1.10500")}, "a buy stop loss must be below the entry price"),
        ({"direction": "sell", "stop_loss": D("1.09500")}, "a sell stop loss must be above"),
        ({"stop_loss": D("0")}, "stop loss must be a positive number"),
        ({"stop_loss": D("1.095105")}, "is not a multiple of the tick size"),
        ({"stop_loss": D("1.10005")}, "below the broker stops level"),
    ],
    ids=["missing", "buy-wrong-side", "sell-wrong-side", "zero", "off-increment", "too-close"],
)
def test_invalid_stop_loss_is_rejected(request_overrides, message):
    result = size_position(snapshot(), buy_eurusd(**request_overrides), config(), now=NOW)
    assert message in rejection(result)


def test_executable_entry_must_match_the_current_fill_price():
    # An "executable" buy below the ask would leave the spread out of the loss.
    result = size_position(snapshot(), buy_eurusd(entry=D("1.10000")), config(), now=NOW)
    assert "does not match the current ask 1.10010" in rejection(result)


def test_market_stop_level_is_measured_from_the_closing_price():
    # 15 points below the ask entry, but only 5 points below the bid that closes a buy:
    # inside the broker's 10-point stops level.
    result = size_position(snapshot(), buy_eurusd(stop_loss=D("1.09995")), config(), now=NOW)
    assert "from 1.10000 is below the broker stops level" in rejection(result)


# --- data quality -----------------------------------------------------------------------


def test_stale_snapshot_is_rejected():
    result = size_position(snapshot(age=timedelta(minutes=10)), buy_eurusd(), config(), now=NOW)
    assert "snapshot data is stale" in rejection(result)
    assert "account data is stale" in rejection(result)


def test_stale_quote_is_rejected():
    data = snapshot()
    old_quote = data.quotes[0].model_copy(update={"timestamp": NOW - timedelta(minutes=5)})
    data = data.model_copy(update={"quotes": [old_quote, *data.quotes[1:]]})
    assert "EURUSD quote data is stale" in rejection(
        size_position(data, buy_eurusd(), config(), now=NOW)
    )


def test_incomplete_specification_is_rejected():
    data = snapshot(EURUSD={"stops_level_points": None, "point": None})
    assert "specification incomplete, missing point, stops_level_points" in rejection(
        size_position(data, buy_eurusd(), config(), now=NOW)
    )


def test_symbol_not_open_for_trading_is_rejected():
    data = snapshot(EURUSD={"trade_allowed": False})
    assert "not open for full trading" in rejection(
        size_position(data, buy_eurusd(), config(), now=NOW)
    )


def test_unknown_symbol_is_rejected():
    request = buy_eurusd(symbol="XAUUSD.crp")
    assert "quote or instrument specification missing" in rejection(
        size_position(snapshot(), request, config(), now=NOW)
    )


# --- existing exposure ------------------------------------------------------------------


def test_existing_exposure_is_reported_separately_and_not_netted():
    data = snapshot()
    data = data.model_copy(
        update={
            "positions": [
                Position(ticket="1", symbol="EURUSD", direction=Direction.BUY, volume=0.5,
                         entry_price=1.09, profit_account_currency=50.0, timestamp=NOW),
                Position(ticket="2", symbol="XAUUSD", direction=Direction.SELL, volume=0.1,
                         entry_price=2010.0, stop_loss=2020.0, profit_account_currency=-5.0,
                         timestamp=NOW),
            ],
            "pending_orders": [
                PendingOrder(ticket="3", symbol="EURUSD", order_type="BUY_LIMIT", volume=0.2,
                             price=1.095, timestamp=NOW),
            ],
        }
    )  # fmt: skip
    result = size_position(data, buy_eurusd(), config(), now=NOW)

    assert result.accepted and result.volume == D("0.38")  # unchanged by existing exposure
    exposure = result.existing_exposure
    assert exposure is not None
    assert (exposure.open_positions, exposure.buy_volume, exposure.positions_without_stop_loss) == (
        1, 0.5, 1,
    )  # fmt: skip
    assert (exposure.pending_orders, exposure.account_open_positions) == (1, 2)
    assert "not netted" in result.notes[0]


# --- configuration ----------------------------------------------------------------------


@pytest.mark.parametrize("percent", [2.5, 0, -1])
def test_risk_percent_cannot_exceed_two_or_be_non_positive(percent):
    with pytest.raises(ValueError, match="at most 2"):
        parse_sizing_config(
            {"maximum_risk_per_trade_percent": percent,
             "position_sizing": {"maximum_data_age_seconds": 120,
                                 "tick_value_tolerance_percent": 2.0,
                                 "commission_per_lot_round_turn": {}, "slippage_points": {}}}
        )  # fmt: skip


def test_repository_config_is_two_percent_and_rejects_until_costs_are_set():
    repo = load_sizing_config(Path("config/risk.yaml"))
    assert repo.risk_fraction == D("0.02")
    repo = dataclasses.replace(repo, commission_currency="USD")
    assert "commission per lot is not configured" in rejection(
        size_position(snapshot(), buy_eurusd(), repo, now=NOW)
    )


# --- stops level boundaries -------------------------------------------------------------
# Broker stops level: 10 points (0.00010). Bid 1.10000, ask 1.10010.


@pytest.mark.parametrize(
    ("direction", "entry", "stop", "accepted"),
    [
        ("buy", "1.10010", "1.09990", True),  # exactly 10 points below the bid
        ("buy", "1.10010", "1.09991", False),  # one point inside
        ("sell", "1.10000", "1.10020", True),  # exactly 10 points above the ask
        ("sell", "1.10000", "1.10019", False),  # one point inside
    ],
)
def test_market_stops_level_boundary(direction, entry, stop, accepted):
    request = buy_eurusd(direction=direction, entry=D(entry), stop_loss=D(stop))
    result = size_position(snapshot(), request, config(), now=NOW)
    assert result.accepted is accepted
    if not accepted:
        assert "below the broker stops level" in " ".join(result.reasons)


@pytest.mark.parametrize(("direction", "entry"), [("buy", "1.10011"), ("sell", "1.09999")])
def test_executable_entry_one_point_off_the_fill_price_is_rejected(direction, entry):
    stop = "1.09000" if direction == "buy" else "1.11000"
    request = buy_eurusd(direction=direction, entry=D(entry), stop_loss=D(stop))
    assert "does not match the current" in rejection(
        size_position(snapshot(), request, config(), now=NOW)
    )


# --- overnight swap ---------------------------------------------------------------------
# Synthetic EURUSD swap: long -6 points, short +2 points per lot per night; 1 USD per point.


def swap_cost(**request: Any) -> D:
    result = size_position(snapshot(), buy_eurusd(**request), config(), now=NOW)
    assert result.loss_model is not None, result.reasons
    return result.loss_model.swap_per_lot


def test_intraday_trade_has_no_swap():
    assert swap_cost(holding_nights=0) == 0


@pytest.mark.parametrize(("nights", "charged"), [(1, 3), (5, 7), (6, 10)])
def test_swap_assumes_the_triple_swap_night_is_included(nights, charged):
    # Worst case: every run of five trading nights contains the triple-swap night.
    assert swap_cost(holding_nights=nights) == D("6") * charged


def test_swap_credit_never_reduces_the_loss():
    sell = dict(direction="sell", entry=D("1.10000"), stop_loss=D("1.10500"), holding_nights=3)
    assert swap_cost(**sell) == 0


def test_swap_reduces_the_permitted_volume():
    intraday = size_position(snapshot(), buy_eurusd(holding_nights=0), config(), now=NOW)
    overnight = size_position(snapshot(), buy_eurusd(holding_nights=5), config(), now=NOW)
    # 517 USD per lot plus 42 USD swap (6 points x 7 nights): 200 / 559 = 0.357 -> 0.35.
    assert (intraday.volume, overnight.volume) == (D("0.38"), D("0.35"))
    assert overnight.estimated_loss is not None and overnight.estimated_loss <= D("200")


def test_swap_in_points_uses_the_loss_tick_value_in_account_currency():
    result = size_position(snapshot("GBP"), buy_eurusd(holding_nights=1), config("GBP"), now=NOW)
    assert result.loss_model is not None
    # 6 points x about 0.79996 GBP per point x 3 charged nights.
    assert abs(result.loss_model.swap_per_lot - D("14.399")) < D("0.001")


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ({"swap_mode": 5}, "swap mode 5 is not supported"),
        ({"swap_mode": None}, "swap specification missing"),
        ({"swap_long": None}, "swap specification missing"),
    ],
)
def test_overnight_trade_without_usable_swap_data_is_rejected(spec, message):
    data = snapshot(EURUSD=spec)
    result = size_position(data, buy_eurusd(holding_nights=1), config(), now=NOW)
    assert message in rejection(result)
    # The same data is fine for an intraday trade, which incurs no swap.
    assert size_position(data, buy_eurusd(holding_nights=0), config(), now=NOW).accepted


def test_swap_mode_in_account_currency_is_used_directly():
    data = snapshot(EURUSD={"swap_mode": 4, "swap_long": -4.5})
    result = size_position(data, buy_eurusd(holding_nights=1), config(), now=NOW)
    assert result.loss_model is not None and result.loss_model.swap_per_lot == D("13.5")


def test_negative_holding_period_is_rejected():
    assert "holding_nights" in rejection(
        size_position(snapshot(), buy_eurusd(holding_nights=-1), config(), now=NOW)
    )
