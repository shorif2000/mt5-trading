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


def test_example_export_matches_format():
    with open("data/example_mcp_export.json", encoding="utf-8") as handle:
        example = json.load(handle)
    assert example["format"] == EXPORT_FORMAT
    assert example["account_info"]["login"] == "REDACTED"


def test_tick_in_the_future_is_rejected():
    export = valid_export()
    # A tick an hour ahead is what treating broker time as UTC on a UTC+1 server looks like.
    export["symbols"]["EURUSD"]["tick"]["time"] = broker_epoch(NOW + timedelta(hours=1))
    assert "is in the future" in rejection(export)
