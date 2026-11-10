"""Typed domain models used by the read-only research application."""

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Direction(StrEnum):
    BUY = "buy"
    SELL = "sell"


TIMEFRAME_SECONDS: dict[str, int] = {"M15": 900, "H1": 3600, "H4": 14400}

Timeframe = Literal["M15", "H1", "H4"]
AccountTradeMode = Literal["demo", "contest", "real", "unknown"]
PendingOrderType = Literal[
    "BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP", "BUY_STOP_LIMIT", "SELL_STOP_LIMIT"
]


def _require_aware_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp must include a timezone")
    return value


def _check_broker_time(timestamp: datetime, broker_time: datetime | None) -> None:
    """``broker_time`` is the same instant as ``timestamp``, shown in the broker's offset."""
    if broker_time is None:
        return
    _require_aware_timestamp(broker_time)
    if broker_time != timestamp:
        raise ValueError("broker_time must be the same instant as timestamp")


class Candle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    broker_time: datetime | None = None
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
        _check_broker_time(self.timestamp, self.broker_time)
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
    broker_time: datetime | None = None
    point: float = Field(gt=0)
    digits: int = Field(ge=0, le=12)

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_aware(cls, value: datetime) -> datetime:
        return _require_aware_timestamp(value)

    @model_validator(mode="after")
    def ask_must_not_be_below_bid(self) -> "Quote":
        _check_broker_time(self.timestamp, self.broker_time)
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
    # Captured from MT5 symbol_info by the MCP export. Optional here so that hand-built specs
    # stay valid, but the export adapter requires every one of them.
    digits: int | None = Field(default=None, ge=0, le=12)
    point: float | None = Field(default=None, gt=0)
    tick_value_profit: float | None = Field(
        default=None, gt=0, description="Value of one tick for a winning move, account currency"
    )
    tick_value_loss: float | None = Field(
        default=None, gt=0, description="Value of one tick for a losing move, account currency"
    )
    stops_level_points: int | None = Field(
        default=None, ge=0, description="Minimum SL/TP distance from price, in points"
    )
    freeze_level_points: int | None = Field(
        default=None, ge=0, description="Distance within which orders cannot be modified"
    )
    calc_mode: int | None = Field(
        default=None, ge=0, description="Raw MT5 SYMBOL_TRADE_CALC_MODE (profit/margin formula)"
    )
    margin_currency: str | None = None
    margin_initial: float | None = Field(default=None, ge=0)
    margin_maintenance: float | None = Field(default=None, ge=0)
    margin_hedged: float | None = Field(default=None, ge=0)

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
    broker_time: datetime | None = None

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_aware(cls, value: datetime) -> datetime:
        return _require_aware_timestamp(value)

    @model_validator(mode="after")
    def broker_time_must_match(self) -> "Position":
        _check_broker_time(self.timestamp, self.broker_time)
        return self


class PendingOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    order_type: PendingOrderType
    volume: float = Field(gt=0)
    price: float = Field(gt=0)
    stop_limit_price: float | None = Field(default=None, gt=0)
    stop_loss: float | None = Field(default=None, gt=0)
    take_profit: float | None = Field(default=None, gt=0)
    timestamp: datetime
    broker_time: datetime | None = None
    expiration: datetime | None = None

    @field_validator("timestamp", "expiration")
    @classmethod
    def timestamps_must_be_aware(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _require_aware_timestamp(value)

    @model_validator(mode="after")
    def broker_time_must_match(self) -> "PendingOrder":
        _check_broker_time(self.timestamp, self.broker_time)
        return self


class CandleSeries(BaseModel):
    """Completed candles only, oldest first. ``as_of`` is the UTC moment completion is judged."""

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1)
    timeframe: Timeframe
    as_of: datetime
    candles: list[Candle] = Field(min_length=1)

    @field_validator("as_of")
    @classmethod
    def as_of_must_be_aware(cls, value: datetime) -> datetime:
        return _require_aware_timestamp(value)

    @model_validator(mode="after")
    def candles_must_be_ordered_and_completed(self) -> "CandleSeries":
        duration = timedelta(seconds=TIMEFRAME_SECONDS[self.timeframe])
        for previous, current in zip(self.candles, self.candles[1:], strict=False):
            if current.timestamp <= previous.timestamp:
                raise ValueError("Candles must be strictly ascending with no duplicates")
        if self.candles[-1].timestamp + duration > self.as_of:
            raise ValueError("Candle series must not include the currently forming candle")
        return self


class AccountSnapshot(BaseModel):
    """Account state as reported by MT5.

    MT5 account info carries no broker timestamp. ``timestamp`` is when collection was
    recorded on this machine, not a broker-generated time and not proof that the account
    figures are fresh.
    """

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
    trade_mode: AccountTradeMode | None = None
    leverage: int | None = Field(default=None, ge=1)
    margin_mode: int | None = Field(default=None, ge=0, description="Raw MT5 ACCOUNT_MARGIN_MODE")
    stop_out_mode: int | None = Field(
        default=None, ge=0, description="Raw MT5 ACCOUNT_MARGIN_SO_MODE: 0 percent, 1 money"
    )
    margin_call_level: float | None = Field(default=None, ge=0)
    stop_out_level: float | None = Field(default=None, ge=0)
    timestamp: datetime = Field(
        description="Local collection time (UTC); not a broker timestamp or proof of freshness"
    )

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_aware(cls, value: datetime) -> datetime:
        return _require_aware_timestamp(value)


class MarketSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account: AccountSnapshot
    quotes: list[Quote]
    instruments: list[InstrumentSpec]
    candles: list[CandleSeries] = Field(default_factory=list)
    positions: list[Position] = Field(default_factory=list)
    pending_orders: list[PendingOrder] = Field(default_factory=list)
    broker_utc_offset_seconds: int | None = None
    generated_at: datetime
    source: str = "manual_or_mcp_export"

    @field_validator("generated_at")
    @classmethod
    def generated_at_must_be_aware(cls, value: datetime) -> datetime:
        return _require_aware_timestamp(value)
