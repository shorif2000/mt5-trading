from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from trading.models import Quote


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
