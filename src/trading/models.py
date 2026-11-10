"""Typed domain models used by the read-only research application."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Direction(StrEnum):
    BUY = "buy"
    SELL = "sell"


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
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Candle timestamp must include a timezone")
        return value

    @field_validator("high")
    @classmethod
    def high_must_cover_ohlc(cls, value: float, info):
        low = info.data.get("low")
        if low is not None and value < low:
            raise ValueError("Candle high cannot be below low")
        return value


class Quote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str
    bid: float = Field(gt=0)
    ask: float = Field(gt=0)
    timestamp: datetime
    point: float = Field(gt=0)
    digits: int = Field(ge=0, le=12)

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Quote timestamp must include a timezone")
        return value

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
    symbol: str
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


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticket: str
    symbol: str
    direction: Direction
    volume: float = Field(gt=0)
    entry_price: float = Field(gt=0)
    stop_loss: float | None = None
    take_profit: float | None = None
    profit_account_currency: float
    timestamp: datetime


class AccountSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    login: str
    server: str
    currency: str
    balance: float
    credit: float
    equity: float
    margin: float
    free_margin: float
    margin_level_percent: float | None = None
    timestamp: datetime


class MarketSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account: AccountSnapshot
    quotes: list[Quote]
    instruments: list[InstrumentSpec]
    positions: list[Position] = []
    pending_orders_count: int = Field(default=0, ge=0)
    generated_at: datetime
    source: str = "manual_or_mcp_export"

    @field_validator("generated_at")
    @classmethod
    def generated_at_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must include a timezone")
        return value
