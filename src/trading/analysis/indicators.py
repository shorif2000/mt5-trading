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


def ema_series(values: Sequence[float], period: int) -> list[float | None]:
    """EMA at every index, seeded with the SMA of the first ``period`` values. A value at index
    i uses only values[0..i], so it never looks ahead. None until enough values exist."""
    if period <= 0:
        raise ValueError("period must be positive")
    result: list[float | None] = [None] * len(values)
    if len(values) < period:
        return result
    alpha = 2 / (period + 1)
    current = sum(values[:period]) / period
    result[period - 1] = current
    for index in range(period, len(values)):
        current = alpha * values[index] + (1 - alpha) * current
        result[index] = current
    return result


def atr_series(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int
) -> list[float | None]:
    """ATR at every index as the simple average of the last ``period`` true ranges (the MT5
    ATR method, as ``atr`` above). Uses only data up to each index."""
    if period <= 0:
        raise ValueError("period must be positive")
    ranges = true_ranges(highs, lows, closes)
    result: list[float | None] = [None] * len(ranges)
    running = 0.0
    for index, value in enumerate(ranges):
        running += value
        if index >= period:
            running -= ranges[index - period]
        if index >= period - 1:
            result[index] = running / period
    return result
