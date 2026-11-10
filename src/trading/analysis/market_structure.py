"""Basic descriptive market structure helpers. These are not standalone trade signals."""

from trading.models import Candle


def recent_range(candles: list[Candle], period: int) -> tuple[float, float]:
    if period <= 0:
        raise ValueError("period must be positive")
    if len(candles) < period:
        raise ValueError(f"Need at least {period} candles, received {len(candles)}")
    window = candles[-period:]
    return max(c.high for c in window), min(c.low for c in window)


def higher_closes(candles: list[Candle], count: int = 3) -> bool:
    if count <= 0 or len(candles) < count + 1:
        return False
    closes = [c.close for c in candles[-(count + 1):]]
    return all(a < b for a, b in zip(closes, closes[1:]))


def lower_closes(candles: list[Candle], count: int = 3) -> bool:
    if count <= 0 or len(candles) < count + 1:
        return False
    closes = [c.close for c in candles[-(count + 1):]]
    return all(a > b for a, b in zip(closes, closes[1:]))
