"""Conservative placeholder for the trend-pullback research hypothesis.

It deliberately does not generate an executable entry. The exact entry rules and parameters
must be specified, backtested and reviewed before this strategy is enabled.
"""

from trading.models import Candle
from trading.strategies.base import SignalStatus, StrategyResult


def evaluate_trend_pullback(
    symbol: str,
    h4: list[Candle],
    h1: list[Candle],
    m15: list[Candle],
    *,
    enabled: bool = False,
) -> StrategyResult:
    if not enabled:
        return StrategyResult(
            symbol, SignalStatus.BLOCKED, None,
            ("Strategy is disabled pending parameterisation and validation.",),
        )
    if min(len(h4), len(h1), len(m15)) < 30:
        return StrategyResult(
            symbol, SignalStatus.INSUFFICIENT_DATA, None,
            ("At least 30 candles per timeframe are required for this research prototype.",),
        )
    return StrategyResult(
        symbol, SignalStatus.NO_SETUP, None,
        ("Entry rules have not been approved; no trade signal is generated.",),
    )
