"""Small deterministic indicator functions with no external data dependencies."""

from collections.abc import Sequence


def sma(values: Sequence[float], period: int) -> float:
    if period <= 0:
        raise ValueError("period must be positive")
    if len(values) < period:
        raise ValueError(f"Need at least {period} values, received {len(values)}")
    return sum(values[-period:]) / period


def true_ranges(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]
) -> list[float]:
    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("highs, lows and closes must have equal lengths")
    if not highs:
        return []
    ranges: list[float] = []
    for index, (high, low) in enumerate(zip(highs, lows, strict=True)):
        previous_close = closes[index - 1] if index else closes[index]
        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    return ranges


def atr(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int
) -> float:
    if period <= 0:
        raise ValueError("period must be positive")
    ranges = true_ranges(highs, lows, closes)
    if len(ranges) < period:
        raise ValueError(f"Need at least {period} candles, received {len(ranges)}")
    return sum(ranges[-period:]) / period
