"""Typed domain models used by the read-only research application."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Direction(StrEnum):
    BUY = "buy"
    SELL = "sell"


def _require_aware_timestamp(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
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
        return _require_aware_timestamp(value, "Candle timestamp")

    @model_validator(mode="after")
    def validate_ohlc(self) -> "Candle":
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("Candle high must be at least the open, close and low")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("Candle low must be no greater than the open, close and high")
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
        return _require_aware_timestamp(value, "Quote timestamp")

    @field_validator("ask")
    @classmethod
    def ask_must_not_be_below_bid(cls, value: float, info):
        bid = info.data.get("bid")
        if bid is not None and value < bid:
            raise ValueError("Ask cannot be below bid")
        return value

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
    def validate_volume_limits(self) -> "InstrumentSpec":
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
        return _require_aware_timestamp(value, "Position timestamp")


class AccountSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login: str = Field(min_length=1)
    server: str = Field(min_length=1)
    currency: str = Field(min_length=1)
    balance: float
    credit: float
    equity: float
    margin: float
    free_margin: float
    margin_level_percent: float | None = None
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_aware(cls, value: datetime) -> datetime:
        return _require_aware_timestamp(value, "Account timestamp")


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
        return _require_aware_timestamp(value, "generated_at")

    @model_validator(mode="after")
    def reject_duplicate_market_data(self) -> "MarketSnapshot":
        quote_symbols = [quote.symbol for quote in self.quotes]
        instrument_symbols = [instrument.symbol for instrument in self.instruments]
        if len(quote_symbols) != len(set(quote_symbols)):
            raise ValueError("Snapshot contains duplicate quote symbols")
        if len(instrument_symbols) != len(set(instrument_symbols)):
            raise ValueError("Snapshot contains duplicate instrument specifications")
        return self
