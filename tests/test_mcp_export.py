"""Business rules for turning mocked read-only MT5 MCP responses into a validated snapshot."""

import copy
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from trading.market_data.mcp_export import (
    EXPORT_FORMAT,
    ExportRejected,
    ExportSettings,
    build_snapshot,
    load_mcp_export,
)

OFFSET = 7200  # broker server is UTC+2
# Tuesday, mid-session. Export taken 30 s into a new M15 bar.
NOW = datetime(2026, 11, 10, 10, 0, 30, tzinfo=UTC)
SYMBOLS = {
    "EURUSD": (1.17259, 1.17272, 0.00001, 5),
    "GBPUSD": (1.33010, 1.33025, 0.00001, 5),
    "USDJPY": (151.201, 151.215, 0.001, 3),
    "XAUUSD": (4726.77, 4726.98, 0.01, 2),
}
SECONDS = {"M15": 900, "H1": 3600, "H4": 14400}
SETTINGS = ExportSettings(min_completed_candles=10)


def broker_epoch(moment: datetime) -> int:
    return int(moment.timestamp()) + OFFSET


def offset_info() -> dict[str, Any]:
    return {"broker_offset_seconds": OFFSET, "broker_offset_confident": True}


def rates(symbol: str, timeframe: str, price: float, bars: int = 20) -> dict[str, Any]:
    """``bars`` bars ending with the bar that is still forming at NOW (as MT5 returns)."""
    step = SECONDS[timeframe]
    forming_open = (broker_epoch(NOW) // step) * step
    rows = [
        {
            "time": forming_open - step * i,
            "open": price,
            "high": price * 1.001,
            "low": price * 0.999,
            "close": price,
            "tick_volume": 100,
            "spread": 12,
            "real_volume": 0,
        }
        for i in reversed(range(bars))
    ]
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "count": len(rows),
        "truncated": False,
        **offset_info(),
        "rates": rows,
    }


def valid_export() -> dict[str, Any]:
    symbols = {}
    for name, (bid, ask, point, digits) in SYMBOLS.items():
        symbols[name] = {
            "symbol_info": {
                "name": name,
                "point": point,
                "digits": digits,
                "trade_contract_size": 100 if name == "XAUUSD" else 100000,
                "trade_tick_size": point,
                "trade_tick_value": 0.75,
                "volume_min": 0.01,
                "volume_max": 100,
                "volume_step": 0.01,
                "trade_mode": 4,
                "currency_base": name[:3],
                "currency_profit": name[3:],
            },
            "tick": {
                "time": broker_epoch(NOW - timedelta(seconds=2)),
                "bid": bid,
                "ask": ask,
                **offset_info(),
            },
            "rates": {tf: rates(name, tf, bid) for tf in ("H4", "H1", "M15")},
        }
    return {
        "format": EXPORT_FORMAT,
        "exported_at_utc": NOW.isoformat(),
        "terminal_status": {
            "mcp_trading_enabled": False,
            "bridge_reachable": True,
            "bridge": {"trading_allowed_by_bridge": False},
            "terminal": {"connected": True, "trade_allowed": False},
            **offset_info(),
        },
        "account_info": {
            "login": 12345678,
            "server": "Example-Demo",
            "currency": "GBP",
            "trade_mode": 0,
            "balance": 1000.0,
            "credit": 0.0,
            "equity": 1000.0,
            "margin": 0.0,
            "margin_free": 1000.0,
            "margin_level": 0.0,
        },
        "positions": {"count": 0, **offset_info(), "positions": []},
        "orders": {"count": 0, **offset_info(), "orders": []},
        "symbols": symbols,
    }


def rejection(export: dict[str, Any]) -> str:
    with pytest.raises(ExportRejected) as info:
        build_snapshot(export, now=NOW, settings=SETTINGS)
    return " | ".join(info.value.reasons)


def test_valid_export_produces_snapshot_with_completed_candles_only():
    snapshot = build_snapshot(valid_export(), now=NOW, settings=SETTINGS)

    assert {q.symbol for q in snapshot.quotes} == set(SYMBOLS)
    assert len(snapshot.candles) == 12
    m15 = next(s for s in snapshot.candles if s.symbol == "EURUSD" and s.timeframe == "M15")
    # The bar opened at 10:00 UTC is still forming at 10:00:30 and must be dropped.
    assert len(m15.candles) == 19
    assert m15.candles[-1].timestamp == datetime(2026, 11, 10, 9, 45, tzinfo=UTC)


def test_broker_and_utc_timestamps_are_distinct_but_same_instant():
    snapshot = build_snapshot(valid_export(), now=NOW, settings=SETTINGS)
    candle = snapshot.candles[0].candles[-1]

    assert candle.timestamp.utcoffset() == timedelta(0)
    assert candle.broker_time is not None
    assert candle.broker_time.utcoffset() == timedelta(seconds=OFFSET)
    assert candle.broker_time == candle.timestamp
    assert snapshot.broker_utc_offset_seconds == OFFSET


def test_account_login_is_redacted_and_type_reported():
    snapshot = build_snapshot(valid_export(), now=NOW, settings=SETTINGS)

    assert snapshot.account.login == "REDACTED"
    assert "12345678" not in snapshot.model_dump_json()
    assert snapshot.account.trade_mode == "demo"
    assert snapshot.account.margin_level_percent is None


# --- quotes -----------------------------------------------------------------------------


def test_stale_quote_is_rejected():
    export = valid_export()
    export["symbols"]["EURUSD"]["tick"]["time"] = broker_epoch(NOW - timedelta(minutes=10))
    assert "EURUSD tick: stale quote" in rejection(export)


def test_quote_with_ask_below_bid_is_rejected():
    export = valid_export()
    export["symbols"]["GBPUSD"]["tick"]["ask"] = 1.0
    assert "Ask cannot be below bid" in rejection(export)


def test_zero_bid_is_rejected():
    export = valid_export()
    export["symbols"]["USDJPY"]["tick"]["bid"] = 0
    assert "USDJPY tick" in rejection(export)


def test_non_numeric_price_is_rejected():
    export = valid_export()
    export["symbols"]["XAUUSD"]["tick"]["bid"] = "4726.77"
    assert "'bid' must be a number" in rejection(export)


def test_missing_symbol_is_rejected():
    export = valid_export()
    del export["symbols"]["XAUUSD"]
    assert "missing 'XAUUSD'" in rejection(export)


# --- candles ----------------------------------------------------------------------------


def test_missing_candle_data_is_rejected():
    export = valid_export()
    export["symbols"]["EURUSD"]["rates"]["H1"]["rates"] = []
    export["symbols"]["EURUSD"]["rates"]["H1"]["count"] = 0
    assert "EURUSD H1 rates: missing candle data" in rejection(export)


def test_too_few_completed_candles_are_rejected():
    export = valid_export()
    export["symbols"]["EURUSD"]["rates"]["M15"] = rates("EURUSD", "M15", 1.17, bars=3)
    assert "2 completed candles (need 10)" in rejection(export)


def test_missing_timeframe_is_rejected():
    export = valid_export()
    del export["symbols"]["GBPUSD"]["rates"]["H4"]
    assert "GBPUSD H4 rates" in rejection(export)


def test_intraday_gap_in_candles_is_rejected():
    export = valid_export()
    rows = export["symbols"]["EURUSD"]["rates"]["M15"]["rates"]
    del rows[3:9]  # 90 minutes of bars missing mid-session
    assert "EURUSD M15 rates: missing candles between" in rejection(export)


def test_weekend_gap_is_accepted():
    export = valid_export()
    friday_close = datetime(2026, 11, 6, 21, 0, tzinfo=UTC)
    sunday_open = datetime(2026, 11, 8, 22, 0, tzinfo=UTC)
    rows = export["symbols"]["EURUSD"]["rates"]["H1"]["rates"]
    # Rebuild H1 as: 5 bars to Friday's close, then hourly from Sunday's open to NOW.
    before = [broker_epoch(friday_close - timedelta(hours=h)) for h in range(5, 0, -1)]
    after_hours = int((NOW - sunday_open).total_seconds() // 3600)
    after = [broker_epoch(sunday_open + timedelta(hours=h)) for h in range(after_hours + 1)]
    template = rows[0]
    export["symbols"]["EURUSD"]["rates"]["H1"]["rates"] = [
        {**template, "time": t} for t in before + after
    ]
    export["symbols"]["EURUSD"]["rates"]["H1"]["count"] = len(before) + len(after)

    build_snapshot(export, now=NOW, settings=SETTINGS)


def test_stale_candles_are_rejected():
    export = valid_export()
    rows = export["symbols"]["EURUSD"]["rates"]["M15"]["rates"]
    del rows[-3:]  # latest completed bar is 45 minutes old
    assert "EURUSD M15 rates: stale" in rejection(export)


def test_candles_in_the_future_are_rejected():
    export = valid_export()
    rows = export["symbols"]["EURUSD"]["rates"]["M15"]["rates"]
    rows.append({**rows[-1], "time": rows[-1]["time"] + 900})
    export["symbols"]["EURUSD"]["rates"]["M15"]["count"] += 1
    assert "more than one incomplete candle" in rejection(export)


def test_unordered_candles_are_rejected():
    export = valid_export()
    rows = export["symbols"]["EURUSD"]["rates"]["M15"]["rates"]
    rows[2], rows[3] = rows[3], rows[2]
    assert "not strictly ascending" in rejection(export)


def test_malformed_ohlc_is_rejected():
    export = valid_export()
    export["symbols"]["EURUSD"]["rates"]["H4"]["rates"][0]["high"] = 0.5
    assert "EURUSD H4 rates" in rejection(export)


def test_truncated_rates_are_rejected():
    export = valid_export()
    export["symbols"]["EURUSD"]["rates"]["H4"]["truncated"] = True
    assert "truncated" in rejection(export)


# --- symbol specifications --------------------------------------------------------------


def test_symbol_name_mismatch_is_rejected():
    export = valid_export()
    export["symbols"]["XAUUSD"]["symbol_info"]["name"] = "XAUUSD.crp"
    assert "does not match 'XAUUSD'" in rejection(export)


def test_invalid_tick_value_is_rejected():
    export = valid_export()
    export["symbols"]["EURUSD"]["symbol_info"]["trade_tick_value"] = 0
    assert "tick_value" in rejection(export)


def test_missing_contract_size_is_rejected():
    export = valid_export()
    del export["symbols"]["USDJPY"]["symbol_info"]["trade_contract_size"]
    assert "missing 'trade_contract_size'" in rejection(export)


def test_close_only_symbol_is_marked_not_tradeable():
    export = valid_export()
    export["symbols"]["EURUSD"]["symbol_info"]["trade_mode"] = 3
    snapshot = build_snapshot(export, now=NOW, settings=SETTINGS)
    spec = next(i for i in snapshot.instruments if i.symbol == "EURUSD")
    assert spec.trade_allowed is False


# --- timezone handling ------------------------------------------------------------------


def test_unknown_broker_offset_is_rejected():
    export = valid_export()
    export["terminal_status"]["broker_offset_seconds"] = None
    assert "broker UTC offset is unknown" in rejection(export)


def test_unconfident_broker_offset_is_rejected():
    export = valid_export()
    export["terminal_status"]["broker_offset_confident"] = False
    assert "not confident" in rejection(export)


def test_response_with_different_offset_is_rejected():
    export = valid_export()
    export["symbols"]["EURUSD"]["tick"]["broker_offset_seconds"] = 10800
    assert "broker offset differs" in rejection(export)


def test_utc_annotation_disagreeing_with_offset_is_rejected():
    export = valid_export()
    tick = export["symbols"]["EURUSD"]["tick"]
    # Bridge says this is UTC, but it is the broker wall time: treating it as UTC is wrong.
    tick["time_utc"] = datetime.fromtimestamp(tick["time"], tz=UTC).isoformat()
    assert "disagrees with the broker offset" in rejection(export)


def test_timezone_naive_export_time_is_rejected():
    export = valid_export()
    export["exported_at_utc"] = "2026-11-10T10:00:30"
    assert "timezone naive" in rejection(export)


def test_stale_export_is_rejected():
    with pytest.raises(ExportRejected, match="export: stale"):
        build_snapshot(valid_export(), now=NOW + timedelta(minutes=5), settings=SETTINGS)


# --- connection failures and safety -----------------------------------------------------


def test_bridge_unreachable_is_rejected():
    export = valid_export()
    export["terminal_status"] = {
        "mcp_trading_enabled": False,
        "bridge_reachable": False,
        "error": "The bridge is unavailable: connection refused",
    }
    assert "bridge unreachable: The bridge is unavailable" in rejection(export)


def test_terminal_disconnected_from_broker_is_rejected():
    export = valid_export()
    export["terminal_status"]["terminal"]["connected"] = False
    assert "not connected to the broker server" in rejection(export)


def test_failed_tool_call_is_rejected():
    export = valid_export()
    export["positions"] = {"tool_error": "Bridge did not answer within 30s"}
    assert "positions: MCP tool call failed: Bridge did not answer" in rejection(export)


def test_unreadable_export_file_is_rejected(tmp_path):
    path = tmp_path / "export.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ExportRejected, match="cannot read"):
        load_mcp_export(path, now=NOW)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("mcp_trading_enabled",), True),
        (("bridge", "trading_allowed_by_bridge"), True),
        (("terminal", "trade_allowed"), True),
    ],
)
def test_export_is_rejected_unless_trading_is_disabled_everywhere(path, value):
    export = valid_export()
    target = export["terminal_status"]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert "not confirmed disabled" in rejection(export)


# --- positions and pending orders -------------------------------------------------------


def test_positions_and_pending_orders_are_retrieved():
    export = valid_export()
    opened = NOW - timedelta(hours=3)
    export["positions"] = {
        "count": 1,
        **offset_info(),
        "positions": [
            {
                "ticket": 501,
                "symbol": "XAUUSD",
                "type": 1,
                "type_name": "SELL",
                "volume": 0.02,
                "price_open": 4730.1,
                "sl": 0.0,
                "tp": 4700.0,
                "profit": 1.5,
                "time": broker_epoch(opened),
            }
        ],
    }
    export["orders"] = {
        "count": 1,
        **offset_info(),
        "orders": [
            {
                "ticket": 902,
                "symbol": "EURUSD",
                "type": 2,
                "volume_current": 0.01,
                "price_open": 1.165,
                "price_stoplimit": 0.0,
                "sl": 1.16,
                "tp": 0.0,
                "time_setup": broker_epoch(opened),
                "time_expiration": 0,
            }
        ],
    }

    snapshot = build_snapshot(export, now=NOW, settings=SETTINGS)

    position = snapshot.positions[0]
    assert (position.ticket, position.direction, position.volume) == ("501", "sell", 0.02)
    assert position.stop_loss is None and position.take_profit == 4700.0
    assert position.timestamp == opened
    order = snapshot.pending_orders[0]
    assert (order.order_type, order.price, order.take_profit) == ("BUY_LIMIT", 1.165, None)
    assert order.expiration is None


def test_market_order_in_pending_list_is_rejected():
    export = valid_export()
    export["orders"] = {
        "count": 1,
        **offset_info(),
        "orders": [{"ticket": 1, "type": 0, "time_setup": broker_epoch(NOW)}],
    }
    assert "not a pending order type" in rejection(export)


def test_position_count_mismatch_is_rejected():
    export = valid_export()
    export["positions"]["count"] = 2
    assert "count does not match" in rejection(export)


def test_every_problem_is_reported_together():
    export = copy.deepcopy(valid_export())
    export["symbols"]["EURUSD"]["tick"]["ask"] = 1.0
    del export["symbols"]["XAUUSD"]["rates"]["M15"]
    with pytest.raises(ExportRejected) as info:
        build_snapshot(export, now=NOW, settings=SETTINGS)
    assert len(info.value.reasons) == 2


def test_synthetic_example_export_is_valid():
    with open("data/example_mcp_export.json", encoding="utf-8") as handle:
        example = json.load(handle)
    assert example["format"] == EXPORT_FORMAT
    assert example["_note"].startswith("SYNTHETIC EXAMPLE")
    as_of = datetime.fromisoformat(example["exported_at_utc"])
    snapshot = build_snapshot(example, now=as_of, settings=ExportSettings(min_completed_candles=2))
    assert snapshot.account.login == "REDACTED"


def test_tick_in_the_future_is_rejected():
    export = valid_export()
    # A tick an hour ahead is what treating broker time as UTC on a UTC+1 server looks like.
    export["symbols"]["EURUSD"]["tick"]["time"] = broker_epoch(NOW + timedelta(hours=1))
    assert "is in the future" in rejection(export)


# --- broker daylight saving time --------------------------------------------------------
# The broker runs on New York time + 7h: UTC+3 while the US observes DST, UTC+2 otherwise.
# The live offset at NOW (10 Nov 2026) is +2; US DST ended on Sunday 1 Nov 2026 and began on
# Sunday 8 Mar 2026.


def wall(year: int, month: int, day: int, hour: int, minute: int = 0) -> int:
    """MT5 broker epoch for a broker wall-clock time."""
    return int(datetime(year, month, day, hour, minute, tzinfo=UTC).timestamp())


def bridge_utc(epoch: int) -> str:
    """What the bridge writes as ``time_utc``: always the live offset, whatever the date."""
    return datetime.fromtimestamp(epoch - OFFSET, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def h4_across_dst_end() -> dict[str, Any]:
    """EURUSD H4 bars in broker wall time from Thu 29 Oct to the forming bar on Tue 10 Nov."""
    times = []
    day = datetime(2026, 10, 29, tzinfo=UTC)
    while day <= datetime(2026, 11, 10, tzinfo=UTC):
        if day.weekday() < 5:  # the broker has no Saturday or Sunday bars
            for hour in range(0, 24, 4):
                epoch = wall(day.year, day.month, day.day, hour)
                if epoch <= wall(2026, 11, 10, 12):  # 12:00 broker is forming at NOW
                    times.append(epoch)
        day += timedelta(days=1)
    rows = [
        {
            "time": t,
            "time_utc": bridge_utc(t),
            "open": 1.1,
            "high": 1.11,
            "low": 1.09,
            "close": 1.1,
            "tick_volume": 100,
            "spread": 10,
            "real_volume": 0,
        }
        for t in times
    ]
    return {
        "symbol": "EURUSD",
        "timeframe": "H4",
        "count": len(rows),
        "truncated": False,
        **offset_info(),
        "rates": rows,
    }


def eurusd_h4(snapshot) -> list:
    return next(s for s in snapshot.candles if s.symbol == "EURUSD" and s.timeframe == "H4").candles


def test_candles_before_dst_change_use_the_offset_in_force_then():
    export = valid_export()
    export["symbols"]["EURUSD"]["rates"]["H4"] = h4_across_dst_end()

    candles = {
        c.broker_time.replace(tzinfo=None): c
        for c in eurusd_h4(build_snapshot(export, now=NOW, settings=SETTINGS))
    }

    friday = candles[datetime(2026, 10, 30, 20)]  # before the change: UTC+3
    assert friday.timestamp == datetime(2026, 10, 30, 17, tzinfo=UTC)
    assert friday.broker_time.utcoffset() == timedelta(hours=3)
    monday = candles[datetime(2026, 11, 2, 0)]  # after the change: UTC+2
    assert monday.timestamp == datetime(2026, 11, 1, 22, tzinfo=UTC)
    assert monday.broker_time.utcoffset() == timedelta(hours=2)


def test_weekend_across_dst_change_is_not_reported_as_a_gap():
    export = valid_export()
    export["symbols"]["EURUSD"]["rates"]["H4"] = h4_across_dst_end()
    build_snapshot(export, now=NOW, settings=SETTINGS)  # does not raise


def test_bridge_utc_annotation_using_live_offset_is_accepted_for_old_bars():
    # The bridge's time_utc is one hour off for bars before the change; it is checked for
    # consistency with the live offset and not used as the timestamp.
    export = valid_export()
    series = h4_across_dst_end()
    export["symbols"]["EURUSD"]["rates"]["H4"] = series
    old = series["rates"][0]
    assert old["time_utc"] == "2026-10-28T22:00:00Z"  # bridge value (+2)

    candle = eurusd_h4(build_snapshot(export, now=NOW, settings=SETTINGS))[0]
    assert candle.timestamp == datetime(2026, 10, 28, 21, tzinfo=UTC)  # correct value (+3)


def test_position_and_order_times_across_dst_changes():
    export = valid_export()
    export["positions"] = {
        "count": 2,
        **offset_info(),
        "positions": [
            {  # opened Fri 30 Oct 10:00 broker, before the November change (UTC+3)
                "ticket": 1,
                "symbol": "EURUSD",
                "type": 0,
                "volume": 0.1,
                "price_open": 1.1,
                "sl": 0.0,
                "tp": 0.0,
                "profit": 0.0,
                "time": wall(2026, 10, 30, 10),
            },
            {  # opened Mon 2 Nov 10:00 broker, after the change (UTC+2)
                "ticket": 2,
                "symbol": "EURUSD",
                "type": 1,
                "volume": 0.1,
                "price_open": 1.1,
                "sl": 0.0,
                "tp": 0.0,
                "profit": 0.0,
                "time": wall(2026, 11, 2, 10),
            },
        ],
    }
    export["orders"] = {
        "count": 2,
        **offset_info(),
        "orders": [
            {  # placed Fri 6 Mar, before US DST began (UTC+2); expires after it (UTC+3)
                "ticket": 3,
                "symbol": "GBPUSD",
                "type": 2,
                "volume_current": 0.1,
                "price_open": 1.2,
                "price_stoplimit": 0.0,
                "sl": 0.0,
                "tp": 0.0,
                "time_setup": wall(2026, 3, 6, 10),
                "time_expiration": wall(2026, 3, 9, 10),
            },
            {  # placed Mon 9 Mar, after US DST began (UTC+3)
                "ticket": 4,
                "symbol": "GBPUSD",
                "type": 3,
                "volume_current": 0.1,
                "price_open": 1.3,
                "price_stoplimit": 0.0,
                "sl": 0.0,
                "tp": 0.0,
                "time_setup": wall(2026, 3, 9, 10),
                "time_expiration": 0,
            },
        ],
    }

    snapshot = build_snapshot(export, now=NOW, settings=SETTINGS)

    before, after = snapshot.positions
    assert before.timestamp == datetime(2026, 10, 30, 7, tzinfo=UTC)
    assert before.broker_time is not None and before.broker_time.utcoffset() == timedelta(hours=3)
    assert after.timestamp == datetime(2026, 11, 2, 8, tzinfo=UTC)
    assert after.broker_time is not None and after.broker_time.utcoffset() == timedelta(hours=2)
    winter, summer = snapshot.pending_orders
    assert winter.timestamp == datetime(2026, 3, 6, 8, tzinfo=UTC)
    assert winter.expiration == datetime(2026, 3, 9, 7, tzinfo=UTC)
    assert summer.timestamp == datetime(2026, 3, 9, 7, tzinfo=UTC)


@pytest.mark.parametrize(
    "broker_wall",
    [
        wall(2026, 11, 1, 8, 30),  # New York 01:30 on 1 Nov 2026 happened twice
        wall(2026, 3, 8, 9, 30),  # New York 02:30 on 8 Mar 2026 never happened
    ],
    ids=["repeated", "skipped"],
)
def test_broker_time_at_a_dst_change_is_rejected(broker_wall):
    export = valid_export()
    export["positions"] = {
        "count": 1,
        **offset_info(),
        "positions": [
            {
                "ticket": 1,
                "symbol": "EURUSD",
                "type": 0,
                "volume": 0.1,
                "price_open": 1.1,
                "sl": 0.0,
                "tp": 0.0,
                "profit": 0.0,
                "time": broker_wall,
            }
        ],
    }
    assert "skipped or repeated by a daylight saving change" in rejection(export)


def test_rule_that_disagrees_with_live_offset_is_rejected():
    settings = ExportSettings(min_completed_candles=10, broker_timezone="UTC", broker_shift_hours=3)
    with pytest.raises(ExportRejected, match="does not match the configured broker time-zone rule"):
        build_snapshot(valid_export(), now=NOW, settings=settings)


def test_unknown_broker_timezone_is_rejected():
    settings = ExportSettings(min_completed_candles=10, broker_timezone="Mars/Olympus")
    with pytest.raises(ExportRejected, match="invalid broker timezone"):
        build_snapshot(valid_export(), now=NOW, settings=settings)


# --- clock skew and offset metadata -----------------------------------------------------


def test_bar_closing_within_clock_skew_is_treated_as_forming():
    export = valid_export()
    just_after_close = datetime(2026, 11, 10, 10, 0, 3, tzinfo=UTC)
    export["exported_at_utc"] = just_after_close.isoformat()

    cautious = build_snapshot(export, now=NOW, settings=SETTINGS)
    m15 = next(s for s in cautious.candles if s.symbol == "EURUSD" and s.timeframe == "M15")
    # The 09:45 bar closed 3 s before the export, inside the 5 s skew allowance.
    assert m15.candles[-1].timestamp == datetime(2026, 11, 10, 9, 30, tzinfo=UTC)

    trusting = ExportSettings(min_completed_candles=10, clock_skew_seconds=0)
    snapshot = build_snapshot(export, now=NOW, settings=trusting)
    m15 = next(s for s in snapshot.candles if s.symbol == "EURUSD" and s.timeframe == "M15")
    assert m15.candles[-1].timestamp == datetime(2026, 11, 10, 9, 45, tzinfo=UTC)


@pytest.mark.parametrize(
    "path",
    [
        ("symbols", "EURUSD", "tick"),
        ("symbols", "EURUSD", "rates", "H1"),
        ("positions",),
        ("orders",),
    ],
    ids=["tick", "rates", "positions", "orders"],
)
def test_missing_offset_metadata_is_rejected(path):
    export = valid_export()
    target = export
    for key in path:
        target = target[key]
    del target["broker_offset_seconds"]
    assert "missing broker offset metadata" in rejection(export)
