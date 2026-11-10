"""Typed domain models used by the read-only research application."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Direction(StrEnum):
    BUY = "buy"
    SELL = "sell"


def _require_aware_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp must include a timezone")
    return value


class Candle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(ge=0)

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_aware(cls, value: datetime) -> datetime:
        return _require_aware_timestamp(value)

    @model_validator(mode="after")
    def validate_ohlc_relationships(self) -> "Candle":
        if self.high < self.low:
            raise ValueError("Candle high cannot be below low")
        if not self.low <= self.open <= self.high:
            raise ValueError("Candle open must be between low and high")
        if not self.low <= self.close <= self.high:
            raise ValueError("Candle close must be between low and high")
        return self


class Quote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1)
    bid: float = Field(gt=0)
    ask: float = Field(gt=0)
    timestamp: datetime
    point: float = Field(gt=0)
    digits: int = Field(ge=0, le=12)

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_aware(cls, value: datetime) -> datetime:
        return _require_aware_timestamp(value)

    @model_validator(mode="after")
    def ask_must_not_be_below_bid(self) -> "Quote":
        if self.ask < self.bid:
            raise ValueError("Ask cannot be below bid")
        return self

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def spread_points(self) -> float:
        return self.spread / self.point


class InstrumentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1)
    base_currency: str | None = None
    quote_currency: str | None = None
    contract_size: float = Field(gt=0)
    tick_size: float = Field(gt=0)
    tick_value: float = Field(gt=0)
    volume_min: float = Field(gt=0)
    volume_max: float = Field(gt=0)
    volume_step: float = Field(gt=0)
    trade_allowed: bool
    calculation_currency: str | None = None

    @model_validator(mode="after")
    def maximum_volume_must_cover_minimum(self) -> "InstrumentSpec":
        if self.volume_max < self.volume_min:
            raise ValueError("Maximum volume cannot be below minimum volume")
        return self


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    direction: Direction
    volume: float = Field(gt=0)
    entry_price: float = Field(gt=0)
    stop_loss: float | None = Field(default=None, gt=0)
    take_profit: float | None = Field(default=None, gt=0)
    profit_account_currency: float
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_aware(cls, value: datetime) -> datetime:
        return _require_aware_timestamp(value)


class AccountSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login: str = Field(min_length=1)
    server: str = Field(min_length=1)
    currency: str = Field(min_length=1)
    balance: float
    credit: float
    equity: float
    margin: float = Field(ge=0)
    free_margin: float
    margin_level_percent: float | None = Field(default=None, ge=0)
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_aware(cls, value: datetime) -> datetime:
        return _require_aware_timestamp(value)


class MarketSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account: AccountSnapshot
    quotes: list[Quote]
    instruments: list[InstrumentSpec]
    positions: list[Position] = Field(default_factory=list)
    pending_orders_count: int = Field(default=0, ge=0)
    generated_at: datetime
    source: str = "manual_or_mcp_export"

    @field_validator("generated_at")
    @classmethod
    def generated_at_must_be_aware(cls, value: datetime) -> datetime:
        return _require_aware_timestamp(value)
