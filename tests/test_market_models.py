from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from trading.models import Candle, InstrumentSpec, Quote


def test_quote_spread_points():
    quote = Quote(
        symbol="EURUSD",
        bid=1.1,
        ask=1.1002,
        timestamp=datetime.now(UTC),
        point=0.00001,
        digits=5,
    )
    assert quote.spread_points == pytest.approx(20)


def test_quote_rejects_ask_below_bid():
    with pytest.raises(ValidationError):
        Quote(
            symbol="EURUSD",
            bid=1.2,
            ask=1.1,
            timestamp=datetime.now(UTC),
            point=0.00001,
            digits=5,
        )


def test_quote_rejects_timezone_naive_timestamp():
    with pytest.raises(ValidationError, match="timezone"):
        Quote(
            symbol="EURUSD",
            bid=1.1,
            ask=1.1001,
            timestamp=datetime(2026, 1, 1),
            point=0.00001,
            digits=5,
        )


def test_candle_rejects_open_outside_high_low():
    with pytest.raises(ValidationError, match="open must be between"):
        Candle(
            timestamp=datetime.now(UTC),
            open=1.2,
            high=1.15,
            low=1.1,
            close=1.12,
            volume=100,
        )


def test_candle_rejects_close_outside_high_low():
    with pytest.raises(ValidationError, match="close must be between"):
        Candle(
            timestamp=datetime.now(UTC),
            open=1.12,
            high=1.15,
            low=1.1,
            close=1.2,
            volume=100,
        )


def test_instrument_rejects_maximum_volume_below_minimum():
    with pytest.raises(ValidationError, match="Maximum volume"):
        InstrumentSpec(
            symbol="EURUSD",
            contract_size=100000,
            tick_size=0.00001,
            tick_value=1,
            volume_min=0.1,
            volume_max=0.01,
            volume_step=0.01,
            trade_allowed=False,
        )
