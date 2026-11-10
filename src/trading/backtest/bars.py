"""Historical bars as MT5 provides them: bid OHLC plus the bar's spread in points."""

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Bar:
    open_time: datetime  # aware UTC, converted with the DST-aware broker clock
    open: float
    high: float
    low: float
    close: float
    spread_points: int  # MT5 bar spread; the ask is reconstructed as bid + spread

    def __post_init__(self) -> None:
        if self.open_time.tzinfo is None or self.open_time.utcoffset() != timedelta(0):
            raise ValueError("bar open_time must be timezone-aware UTC")
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError(f"invalid OHLC at {self.open_time.isoformat()}")
        if self.spread_points < 0:
            raise ValueError(f"negative spread at {self.open_time.isoformat()}")
