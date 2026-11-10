"""Build a validated MarketSnapshot from an export of read-only MT5 MCP tool responses.

Claude calls the read-only ``mt5`` MCP tools and writes their responses verbatim into one
JSON file (format described in docs/mt5-integration-assessment.md). This module performs
every conversion and validation deterministically. It never connects to MT5.

MT5 reports broker server time as a "fake UTC" epoch: the broker's wall-clock time. The
broker's offset changes with daylight saving time, so one current offset cannot convert
history. Each epoch is converted with the offset the broker's time-zone rule gives *at that
moment* (``BrokerClock``). The rule is checked against the live offset from
``terminal_status``. Every converted timestamp is kept twice: ``timestamp`` in UTC and
``broker_time`` in the broker offset that applied at that moment.
"""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TypeVar
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from trading.market_data.sessions import MarketCalendar
from trading.models import (
    TIMEFRAME_SECONDS,
    AccountSnapshot,
    AccountTradeMode,
    Candle,
    CandleSeries,
    Direction,
    InstrumentSpec,
    MarketSnapshot,
    PendingOrder,
    PendingOrderType,
    Position,
    Quote,
    Timeframe,
)

EXPORT_FORMAT = "mt5-mcp-export/v1"
ACCOUNT_TRADE_MODES: dict[int, AccountTradeMode] = {0: "demo", 1: "contest", 2: "real"}
SYMBOL_TRADE_MODE_FULL = 4
POSITION_DIRECTIONS = {0: Direction.BUY, 1: Direction.SELL}
PENDING_ORDER_TYPES: dict[int, PendingOrderType] = {
    2: "BUY_LIMIT",
    3: "SELL_LIMIT",
    4: "BUY_STOP",
    5: "SELL_STOP",
    6: "BUY_STOP_LIMIT",
    7: "SELL_STOP_LIMIT",
}

T = TypeVar("T")


@dataclass(frozen=True)
class ExportSettings:
    symbols: tuple[str, ...] = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD")
    timeframes: tuple[Timeframe, ...] = ("H4", "H1", "M15")
    max_export_age_seconds: int = 120
    max_quote_age_seconds: int = 120
    min_completed_candles: int = 50
    # Trading sessions and closures (config/market_sessions.yaml). Required: without it no gap
    # or staleness judgement is possible, so every candle series is rejected.
    calendar: MarketCalendar | None = None
    # Allowed difference between this machine's clock and the broker's. Also held back when
    # deciding whether a candle has closed, so a fast local clock cannot accept a forming bar.
    clock_skew_seconds: int = 5
    # Broker wall time = wall time in this IANA zone + shift. The default is the "New York
    # close" convention (UTC+2 in winter, UTC+3 during US daylight saving time), verified for
    # the current broker from its weekly open; see docs/mt5-integration-assessment.md.
    broker_timezone: str = "America/New_York"
    broker_shift_hours: int = 7


class ExportRejected(Exception):
    """The export cannot be used for analysis. ``reasons`` lists every problem found."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


class BrokerClock:
    """Converts MT5 broker epochs with the offset in force at each moment.

    ``live_offset`` is the offset ``terminal_status`` reports now; the bridge used it for every
    ``*_utc`` annotation regardless of date.
    """

    def __init__(self, zone_name: str, shift_hours: int, live_offset: int) -> None:
        self.zone = ZoneInfo(zone_name)
        self.shift = timedelta(hours=shift_hours)
        self.live_offset = live_offset

    def offset_at(self, moment: datetime) -> int:
        zone_offset = moment.astimezone(self.zone).utcoffset()
        if zone_offset is None:
            raise ValueError(f"no UTC offset for {moment.isoformat()} in {self.zone}")
        return int((zone_offset + self.shift).total_seconds())

    def utc(self, epoch: int) -> datetime:
        broker_wall = datetime.fromtimestamp(epoch, tz=UTC).replace(tzinfo=None)
        zone_wall = broker_wall - self.shift
        # A wall time skipped or repeated by a DST change has no single UTC instant.
        candidates = {
            zone_wall.replace(tzinfo=self.zone, fold=fold).astimezone(UTC) for fold in (0, 1)
        }
        valid = [
            moment
            for moment in candidates
            if moment.astimezone(self.zone).replace(tzinfo=None) == zone_wall
        ]
        if len(valid) != 1:
            raise ValueError(
                f"broker time {broker_wall.isoformat()} is skipped or repeated by a daylight "
                "saving change and cannot be converted to UTC unambiguously"
            )
        return valid[0]

    def broker(self, epoch: int) -> datetime:
        moment = self.utc(epoch)
        return moment.astimezone(timezone(timedelta(seconds=self.offset_at(moment))))


# --- primitive field access -------------------------------------------------------------


def _field(record: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in record or record[key] is None:
        raise ValueError(f"{where}: missing '{key}'")
    return record[key]


def _number(record: Mapping[str, Any], key: str, where: str) -> float:
    value = _field(record, key, where)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{where}: '{key}' must be a number, got {value!r}")
    return float(value)


def _integer(record: Mapping[str, Any], key: str, where: str) -> int:
    value = _field(record, key, where)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{where}: '{key}' must be an integer, got {value!r}")
    return int(value)


def _positive_integer(record: Mapping[str, Any], key: str, where: str) -> int:
    value = _integer(record, key, where)
    if value <= 0:
        raise ValueError(f"{where}: '{key}' must be positive, got {value} (not reported by MT5)")
    return value


def _text(record: Mapping[str, Any], key: str, where: str) -> str:
    value = _field(record, key, where)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{where}: '{key}' must be a non-empty string")
    return value


def _optional_price(record: Mapping[str, Any], key: str, where: str) -> float | None:
    """MT5 uses 0 for an unset stop loss, take profit or stop-limit price."""
    value = _number(record, key, where)
    return None if value == 0 else value


def _epoch(record: Mapping[str, Any], key: str, where: str) -> int:
    value = _integer(record, key, where)
    if value <= 0:
        raise ValueError(f"{where}: '{key}' must be a positive broker epoch")
    return value


def _section(container: Mapping[str, Any], key: str, where: str) -> dict[str, Any]:
    value = container.get(key)
    if value is None:
        raise ValueError(f"{where}: missing '{key}'")
    if not isinstance(value, dict):
        raise ValueError(f"{where}: '{key}' must be a JSON object")
    if "tool_error" in value:
        label = key if where == "export" else f"{where} {key}"
        raise ValueError(f"{label}: MCP tool call failed: {value['tool_error']}")
    return value


def _parse_utc(text: object, where: str) -> datetime:
    if not isinstance(text, str):
        raise ValueError(f"{where}: must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{where}: invalid ISO-8601 timestamp {text!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{where}: timestamp {text!r} is timezone naive")
    return parsed.astimezone(UTC)


def _describe(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(
            f"{'.'.join(str(p) for p in error['loc']) or 'value'}: {error['msg']}"
            for error in exc.errors()
        )
    return str(exc)


def _prefixed(where: str, exc: Exception) -> str:
    message = _describe(exc)
    return message if message.startswith(where) else f"{where}: {message}"


def _attempt(reasons: list[str], where: str, build: Callable[[], T]) -> T | None:
    try:
        return build()
    except (ValueError, ValidationError) as exc:
        reasons.append(_prefixed(where, exc))
        return None


# --- time consistency -------------------------------------------------------------------


def _check_utc_annotation(
    record: Mapping[str, Any], key: str, epoch: int, clock: BrokerClock, where: str
) -> None:
    """The bridge's ``<key>_utc`` string, when present, must equal ``epoch - live offset``.

    The bridge applies the current offset to every epoch, so its annotation is wrong for
    times before a DST change. It is therefore checked for consistency with the live offset
    and never used as the UTC value.
    """
    annotated = record.get(f"{key}_utc")
    if annotated is None:
        return
    expected = datetime.fromtimestamp(epoch - clock.live_offset, tz=UTC)
    if _parse_utc(annotated, f"{where}.{key}_utc") != expected:
        raise ValueError(f"{where}: '{key}_utc' disagrees with the broker offset")


def _check_response_offset(response: Mapping[str, Any], offset: int, where: str) -> None:
    """Every tool response carrying broker times must state the offset it was produced with."""
    if "broker_offset_seconds" not in response:
        raise ValueError(f"{where}: missing broker offset metadata")
    if response.get("broker_offset_seconds") != offset:
        raise ValueError(f"{where}: broker offset differs from terminal_status")
    if response.get("broker_offset_confident") is not True:
        raise ValueError(f"{where}: broker offset was not confident")


def _broker_offset(status: Mapping[str, Any]) -> int:
    if status.get("bridge_reachable") is not True:
        raise ValueError(f"terminal_status: bridge unreachable: {status.get('error', 'no detail')}")
    if "terminal_error" in status:
        raise ValueError(f"terminal_status: {status['terminal_error']}")
    terminal = status.get("terminal")
    if not isinstance(terminal, dict) or terminal.get("connected") is not True:
        raise ValueError("terminal_status: MT5 terminal is not connected to the broker server")
    offset = status.get("broker_offset_seconds")
    if isinstance(offset, bool) or not isinstance(offset, int):
        raise ValueError(
            "terminal_status: broker UTC offset is unknown; timestamps cannot be converted"
        )
    if status.get("broker_offset_confident") is not True:
        raise ValueError("terminal_status: broker UTC offset estimate is not confident")
    if offset % 900 or not -12 * 3600 <= offset <= 14 * 3600:
        raise ValueError(f"terminal_status: implausible broker UTC offset {offset}s")
    return offset


def _trading_disabled_reasons(status: Mapping[str, Any]) -> list[str]:
    """Fail closed unless every layer confirms that trading is off."""
    reasons = []
    if status.get("mcp_trading_enabled") is not False:
        reasons.append("terminal_status: MCP trading tools are not confirmed disabled")
    bridge = status.get("bridge")
    if not isinstance(bridge, dict) or bridge.get("trading_allowed_by_bridge") is not False:
        reasons.append("terminal_status: bridge trading is not confirmed disabled")
    terminal = status.get("terminal")
    if isinstance(terminal, dict) and terminal.get("trade_allowed") is not False:
        reasons.append("terminal_status: MT5 Algo Trading is not confirmed disabled")
    return reasons


# --- record conversion ------------------------------------------------------------------


def _account(info: Mapping[str, Any], as_of: datetime) -> AccountSnapshot:
    where = "account_info"
    margin_level = _number(info, "margin_level", where)
    trade_mode = info.get("trade_mode")
    return AccountSnapshot(
        login="REDACTED",
        server=_text(info, "server", where),
        currency=_text(info, "currency", where),
        balance=_number(info, "balance", where),
        credit=_number(info, "credit", where),
        equity=_number(info, "equity", where),
        margin=_number(info, "margin", where),
        free_margin=_number(info, "margin_free", where),
        # MT5 reports 0 when no margin is in use: the level is undefined, not zero.
        margin_level_percent=margin_level if margin_level > 0 else None,
        trade_mode=ACCOUNT_TRADE_MODES.get(trade_mode, "unknown")
        if isinstance(trade_mode, int)
        else "unknown",
        leverage=_positive_integer(info, "leverage", where),
        margin_mode=_integer(info, "margin_mode", where),
        stop_out_mode=_integer(info, "margin_so_mode", where),
        margin_call_level=_number(info, "margin_so_call", where),
        stop_out_level=_number(info, "margin_so_so", where),
        # MT5 account info has no broker timestamp. This is the local collection start time,
        # recorded before account_info was read: not proof that the account data is fresh.
        timestamp=as_of,
    )


def _instrument(symbol: str, info: Mapping[str, Any]) -> InstrumentSpec:
    where = f"{symbol} symbol_info"
    if info.get("name") != symbol:
        raise ValueError(f"{where}: name {info.get('name')!r} does not match {symbol!r}")
    return InstrumentSpec(
        symbol=symbol,
        base_currency=info.get("currency_base"),
        quote_currency=info.get("currency_profit"),
        contract_size=_number(info, "trade_contract_size", where),
        tick_size=_number(info, "trade_tick_size", where),
        tick_value=_number(info, "trade_tick_value", where),
        volume_min=_number(info, "volume_min", where),
        volume_max=_number(info, "volume_max", where),
        volume_step=_number(info, "volume_step", where),
        trade_allowed=_integer(info, "trade_mode", where) == SYMBOL_TRADE_MODE_FULL,
        digits=_integer(info, "digits", where),
        point=_number(info, "point", where),
        tick_value_profit=_number(info, "trade_tick_value_profit", where),
        tick_value_loss=_number(info, "trade_tick_value_loss", where),
        stops_level_points=_integer(info, "trade_stops_level", where),
        freeze_level_points=_integer(info, "trade_freeze_level", where),
        calc_mode=_integer(info, "trade_calc_mode", where),
        margin_currency=_text(info, "currency_margin", where),
        margin_initial=_number(info, "margin_initial", where),
        margin_maintenance=_number(info, "margin_maintenance", where),
        margin_hedged=_number(info, "margin_hedged", where),
        swap_mode=_integer(info, "swap_mode", where),
        swap_long=_number(info, "swap_long", where),
        swap_short=_number(info, "swap_short", where),
        swap_rollover3days=_integer(info, "swap_rollover3days", where),
    )


def _quote(
    symbol: str,
    tick: Mapping[str, Any],
    info: Mapping[str, Any],
    clock: BrokerClock,
    as_of: datetime,
    now: datetime,
    settings: ExportSettings,
) -> Quote:
    where = f"{symbol} tick"
    _check_response_offset(tick, clock.live_offset, where)
    epoch = _epoch(tick, "time", where)
    timestamp = clock.utc(epoch)
    _check_utc_annotation(tick, "time", epoch, clock, where)
    # The export time is taken before collection starts, so a tick may be slightly newer than
    # it. Only a tick newer than the real current time indicates a timezone error.
    if (timestamp - now).total_seconds() > settings.clock_skew_seconds:
        raise ValueError(f"{where}: tick time {timestamp.isoformat()} is in the future")
    age = (as_of - timestamp).total_seconds()
    if age > settings.max_quote_age_seconds:
        raise ValueError(
            f"{where}: stale quote, last tick {timestamp.isoformat()} is {age:.0f}s old "
            f"(limit {settings.max_quote_age_seconds}s)"
        )
    return Quote(
        symbol=symbol,
        bid=_number(tick, "bid", where),
        ask=_number(tick, "ask", where),
        timestamp=timestamp,
        broker_time=clock.broker(epoch),
        point=_number(info, "point", f"{symbol} symbol_info"),
        digits=_integer(info, "digits", f"{symbol} symbol_info"),
    )


def _unexplained_gaps(
    symbol: str, candles: list[Candle], duration: timedelta, calendar: MarketCalendar
) -> list[str]:
    """Missing candles are acceptable only while the market was scheduled to be closed."""
    gaps = []
    for previous, current in zip(candles, candles[1:], strict=False):
        closed = previous.timestamp + duration
        if calendar.open_time(symbol, closed, current.timestamp) > calendar.max_unexplained_gap:
            text = f"{closed.isoformat()} to {current.timestamp.isoformat()}"
            # Reference only: these never accept a gap, they tell a reviewer what to confirm.
            notes = calendar.notes(symbol, closed, current.timestamp)
            gaps.append(f"{text} [{'; '.join(notes)}]" if notes else text)
    return gaps


def _candle_series(
    symbol: str,
    timeframe: Timeframe,
    response: Mapping[str, Any],
    clock: BrokerClock,
    as_of: datetime,
    settings: ExportSettings,
) -> CandleSeries:
    where = f"{symbol} {timeframe} rates"
    if response.get("symbol") != symbol or response.get("timeframe") != timeframe:
        raise ValueError(f"{where}: response is for a different symbol or timeframe")
    if response.get("truncated") is not False:
        raise ValueError(f"{where}: response was truncated or did not report truncation")
    _check_response_offset(response, clock.live_offset, where)
    rows = response.get("rates")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{where}: missing candle data")

    seconds = TIMEFRAME_SECONDS[timeframe]
    duration = timedelta(seconds=seconds)
    candles: list[Candle] = []
    for index, row in enumerate(rows):
        row_where = f"{where}[{index}]"
        if not isinstance(row, dict):
            raise ValueError(f"{row_where}: must be a JSON object")
        epoch = _epoch(row, "time", row_where)
        if epoch % seconds:
            raise ValueError(f"{row_where}: bar time is not aligned to {timeframe}")
        timestamp = clock.utc(epoch)
        _check_utc_annotation(row, "time", epoch, clock, row_where)
        candles.append(
            Candle(
                timestamp=timestamp,
                broker_time=clock.broker(epoch),
                open=_number(row, "open", row_where),
                high=_number(row, "high", row_where),
                low=_number(row, "low", row_where),
                close=_number(row, "close", row_where),
                volume=_number(row, "tick_volume", row_where),
            )
        )

    for previous, current in zip(candles, candles[1:], strict=False):
        if current.timestamp <= previous.timestamp:
            raise ValueError(f"{where}: candles are not strictly ascending")

    # Hold back the clock-skew allowance: a bar only counts as closed once it has closed even
    # if this machine's clock is ahead of the broker's by up to that allowance.
    cutoff = as_of - timedelta(seconds=settings.clock_skew_seconds)
    if sum(1 for c in candles if c.timestamp + duration > as_of) > 1:
        raise ValueError(f"{where}: more than one incomplete candle; bar times are in the future")
    completed = [c for c in candles if c.timestamp + duration <= cutoff]
    if len(completed) < settings.min_completed_candles:
        raise ValueError(
            f"{where}: missing candle data, {len(completed)} completed candles "
            f"(need {settings.min_completed_candles})"
        )
    calendar = settings.calendar
    if calendar is None:
        raise ValueError(f"{where}: no market calendar configured; cannot judge gaps")
    last_close = completed[-1].timestamp + duration
    # Stale only if the market was open for more than one bar since the last completed bar:
    # a daily break, weekend or configured closure is not staleness.
    if calendar.open_time(symbol, last_close, cutoff) > duration:
        raise ValueError(
            f"{where}: stale, latest completed candle closed at {last_close.isoformat()}"
        )
    gaps = _unexplained_gaps(symbol, completed, duration, calendar)
    if gaps:
        raise ValueError(
            f"{where}: missing candles during scheduled market hours between "
            f"{', '.join(gaps)}; if this was a broker holiday or early close, add it to the "
            "market calendar closures as confirmed"
        )
    return CandleSeries(symbol=symbol, timeframe=timeframe, as_of=as_of, candles=completed)


def _rows(response: Mapping[str, Any], key: str, where: str) -> list[dict[str, Any]]:
    rows = response.get(key)
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise ValueError(f"{where}: '{key}' must be a list of objects")
    if response.get("count") != len(rows):
        raise ValueError(f"{where}: count does not match the number of {key}")
    return rows


def _positions(response: Mapping[str, Any], clock: BrokerClock) -> list[Position]:
    _check_response_offset(response, clock.live_offset, "positions")
    positions = []
    for index, row in enumerate(_rows(response, "positions", "positions")):
        where = f"positions[{index}]"
        position_type = _integer(row, "type", where)
        if position_type not in POSITION_DIRECTIONS:
            raise ValueError(f"{where}: unknown position type {position_type}")
        epoch = _epoch(row, "time", where)
        timestamp = clock.utc(epoch)
        _check_utc_annotation(row, "time", epoch, clock, where)
        positions.append(
            Position(
                ticket=str(_integer(row, "ticket", where)),
                symbol=_text(row, "symbol", where),
                direction=POSITION_DIRECTIONS[position_type],
                volume=_number(row, "volume", where),
                entry_price=_number(row, "price_open", where),
                stop_loss=_optional_price(row, "sl", where),
                take_profit=_optional_price(row, "tp", where),
                profit_account_currency=_number(row, "profit", where),
                timestamp=timestamp,
                broker_time=clock.broker(epoch),
            )
        )
    return positions


def _pending_orders(response: Mapping[str, Any], clock: BrokerClock) -> list[PendingOrder]:
    _check_response_offset(response, clock.live_offset, "orders")
    orders = []
    for index, row in enumerate(_rows(response, "orders", "orders")):
        where = f"orders[{index}]"
        order_type = _integer(row, "type", where)
        if order_type not in PENDING_ORDER_TYPES:
            raise ValueError(f"{where}: type {order_type} is not a pending order type")
        epoch = _epoch(row, "time_setup", where)
        timestamp = clock.utc(epoch)
        _check_utc_annotation(row, "time_setup", epoch, clock, where)
        expiration_epoch = _integer(row, "time_expiration", where)
        orders.append(
            PendingOrder(
                ticket=str(_integer(row, "ticket", where)),
                symbol=_text(row, "symbol", where),
                order_type=PENDING_ORDER_TYPES[order_type],
                volume=_number(row, "volume_current", where),
                price=_number(row, "price_open", where),
                stop_limit_price=_optional_price(row, "price_stoplimit", where),
                stop_loss=_optional_price(row, "sl", where),
                take_profit=_optional_price(row, "tp", where),
                timestamp=timestamp,
                broker_time=clock.broker(epoch),
                expiration=clock.utc(expiration_epoch) if expiration_epoch > 0 else None,
            )
        )
    return orders


def _convert_symbol(
    symbol: str,
    data: Mapping[str, Any],
    clock: BrokerClock,
    as_of: datetime,
    now: datetime,
    settings: ExportSettings,
    reasons: list[str],
    quotes: list[Quote],
    instruments: list[InstrumentSpec],
    series: list[CandleSeries],
) -> None:
    """Convert one symbol's responses, recording every problem instead of stopping early."""
    try:
        info = _section(data, "symbol_info", symbol)
        instruments.append(_instrument(symbol, info))
    except (ValueError, ValidationError) as exc:
        reasons.append(_prefixed(symbol, exc))
        info = None
    if info is not None:
        try:
            quotes.append(
                _quote(symbol, _section(data, "tick", symbol), info, clock, as_of, now, settings)
            )
        except (ValueError, ValidationError) as exc:
            reasons.append(_prefixed(f"{symbol} tick", exc))
    try:
        rates = _section(data, "rates", symbol)
    except ValueError as exc:
        reasons.append(str(exc))
        return
    for timeframe in settings.timeframes:
        where = f"{symbol} {timeframe} rates"
        try:
            response = _section(rates, timeframe, f"{symbol} rates")
            series.append(_candle_series(symbol, timeframe, response, clock, as_of, settings))
        except (ValueError, ValidationError) as exc:
            reasons.append(_prefixed(where, exc))


# --- entry points -----------------------------------------------------------------------


def build_snapshot(
    export: Mapping[str, Any], *, now: datetime, settings: ExportSettings | None = None
) -> MarketSnapshot:
    """Validate an MCP export and convert it. Raises ExportRejected listing every problem."""
    settings = settings or ExportSettings()
    reasons: list[str] = []

    if export.get("format") != EXPORT_FORMAT:
        raise ExportRejected([f"export: format must be {EXPORT_FORMAT!r}"])
    as_of = _attempt(
        reasons,
        "export.exported_at_utc",
        lambda: _parse_utc(export.get("exported_at_utc"), "export.exported_at_utc"),
    )
    if as_of is not None:
        age = (now - as_of).total_seconds()
        if age < -settings.clock_skew_seconds:
            reasons.append("export: exported_at_utc is in the future")
        elif age > settings.max_export_age_seconds:
            reasons.append(f"export: stale, exported {age:.0f}s ago")

    status = _attempt(reasons, "export", lambda: _section(export, "terminal_status", "export"))
    offset = None
    if status is not None:
        reasons.extend(_trading_disabled_reasons(status))
        offset = _attempt(reasons, "terminal_status", lambda: _broker_offset(status))
    if as_of is None or offset is None:
        raise ExportRejected(reasons)
    try:
        clock = BrokerClock(settings.broker_timezone, settings.broker_shift_hours, offset)
    except (KeyError, ValueError) as exc:  # unknown IANA zone name
        raise ExportRejected([*reasons, f"settings: invalid broker timezone: {exc}"]) from exc
    rule_offset = clock.offset_at(as_of)
    if rule_offset != offset:
        reasons.append(
            f"terminal_status: broker offset {offset}s does not match the configured broker "
            f"time-zone rule ({settings.broker_timezone} {settings.broker_shift_hours:+d}h gives "
            f"{rule_offset}s); historical timestamps cannot be converted safely"
        )
        raise ExportRejected(reasons)

    account = _attempt(
        reasons, "account_info", lambda: _account(_section(export, "account_info", "export"), as_of)
    )
    positions = _attempt(
        reasons, "positions", lambda: _positions(_section(export, "positions", "export"), clock)
    )
    orders = _attempt(
        reasons, "orders", lambda: _pending_orders(_section(export, "orders", "export"), clock)
    )

    quotes: list[Quote] = []
    instruments: list[InstrumentSpec] = []
    series: list[CandleSeries] = []
    symbols = export.get("symbols")
    if not isinstance(symbols, dict):
        reasons.append("export: missing 'symbols'")
        symbols = {}
    for symbol in settings.symbols:
        try:
            data = _section(symbols, symbol, "symbols")
        except ValueError as exc:
            reasons.append(str(exc))
            continue
        _convert_symbol(
            symbol, data, clock, as_of, now, settings, reasons, quotes, instruments, series
        )

    if reasons or account is None or positions is None or orders is None:
        raise ExportRejected(reasons)
    return MarketSnapshot(
        account=account,
        quotes=quotes,
        instruments=instruments,
        candles=series,
        positions=positions,
        pending_orders=orders,
        broker_utc_offset_seconds=offset,
        generated_at=as_of,
        source="mt5_mcp_export",
    )


def _reject_constant(name: str) -> object:
    raise ValueError(f"invalid JSON constant {name}")


def load_mcp_export(
    path: Path, *, now: datetime, settings: ExportSettings | None = None
) -> MarketSnapshot:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_constant)
    except (OSError, ValueError) as exc:
        raise ExportRejected([f"export: cannot read {path.name}: {exc}"]) from exc
    if not isinstance(payload, dict):
        raise ExportRejected(["export: top level must be a JSON object"])
    return build_snapshot(payload, now=now, settings=settings)
