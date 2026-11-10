"""Strategy contracts and result models."""

from dataclasses import dataclass
from enum import StrEnum

from trading.models import Direction


class SignalStatus(StrEnum):
    CANDIDATE = "candidate"
    NO_SETUP = "no_setup"
    INSUFFICIENT_DATA = "insufficient_data"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class StrategyResult:
    symbol: str
    status: SignalStatus
    direction: Direction | None
    reasons: tuple[str, ...]
    timeframe: str = "H4/H1/M15"
