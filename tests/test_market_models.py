from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from trading.models import Candle, Quote


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
    with pytest.raises(ValidationError, match="must include a timezone"):
        Quote(
            symbol="EURUSD",
            bid=1.1,
            ask=1.1001,
            timestamp=datetime(2026, 11, 10),
            point=0.00001,
            digits=5,
        )


def test_candle_accepts_valid_ohlc():
    candle = Candle(
        timestamp=datetime.now(UTC),
        open=1.1,
        high=1.12,
        low=1.09,
        close=1.11,
        volume=100,
    )
    assert candle.high >= max(candle.open, candle.close, candle.low)
    assert candle.low <= min(candle.open, candle.close, candle.high)


@pytest.mark.parametrize(
    ("open_price", "high", "low", "close"),
    [
        (1.11, 1.10, 1.09, 1.10),
        (1.10, 1.12, 1.11, 1.115),
        (1.10, 1.12, 1.09, 1.13),
    ],
)
def test_candle_rejects_inconsistent_ohlc(open_price, high, low, close):
    with pytest.raises(ValidationError):
        Candle(
            timestamp=datetime.now(UTC),
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=100,
        )


def test_candle_rejects_timezone_naive_timestamp():
    with pytest.raises(ValidationError, match="must include a timezone"):
        Candle(
            timestamp=datetime(2026, 11, 10),
            open=1.1,
            high=1.12,
            low=1.09,
            close=1.11,
            volume=100,
        )
