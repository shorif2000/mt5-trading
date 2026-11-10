"""Read-only history download and conversion of downloaded bars."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from trading.backtest.history_bars import bars_from_rows
from trading.market_data.history import download_rates
from trading.market_data.mcp_collector import READ_ONLY_TOOLS
from trading.market_data.mcp_export import BrokerClock


class RatesSession:
    """Serves M15 rows for any requested range; can fail or truncate one chunk."""

    def __init__(self, fail_from: str | None = None, truncate_from: str | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail_from, self.truncate_from = fail_from, truncate_from

    async def list_tools(self) -> Any:
        return SimpleNamespace(tools=[])

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        assert arguments is not None
        self.calls.append((name, arguments))
        start = datetime.fromisoformat(arguments["start"])
        end = datetime.fromisoformat(arguments["end"])
        rows, t = [], start
        while t < end:
            epoch = int(t.timestamp()) + 7200
            rows.append({"time": epoch, "open": 1, "high": 1, "low": 1, "close": 1, "spread": 20})
            t += timedelta(minutes=15)
        content: dict[str, Any] = {"rates": rows, "truncated": False, "broker_offset_seconds": 7200}
        if arguments["start"].startswith(self.truncate_from or "~"):
            content["truncated"] = True
        if arguments["start"].startswith(self.fail_from or "~"):
            text = SimpleNamespace(text="Bridge did not answer")
            return SimpleNamespace(is_error=True, content=[text], structured_content=None)
        return SimpleNamespace(is_error=False, content=[], structured_content=content)


START, END = datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 3, 1, tzinfo=UTC)


def test_rates_download_in_overlapping_chunks_without_duplicates():
    session = RatesSession()
    result = asyncio.run(download_rates(session, "XAUUSD", "M15", START, END))
    assert {name for name, _ in session.calls} == {"get_rates"} <= READ_ONLY_TOOLS
    assert len(session.calls) == 2  # 30-day chunks, each overlapping the previous by one day
    times = [row["time"] for row in result["rates"]]
    assert times == sorted(set(times)) and result["problems"] == []


@pytest.mark.parametrize(
    ("session", "problem"),
    [(RatesSession(fail_from="2026-01-30"), "Bridge did not answer"),
     (RatesSession(truncate_from="2026-01-30"), "truncated")],
)  # fmt: skip
def test_failed_or_truncated_chunks_are_reported(session, problem):
    result = asyncio.run(download_rates(session, "XAUUSD", "M15", START, END))
    assert len(result["problems"]) == 1 and problem in result["problems"][0]


def broker_epoch(year: int, month: int, day: int, hour: int, minute: int = 0) -> int:
    return int(datetime(year, month, day, hour, minute, tzinfo=UTC).timestamp())


def row(epoch: int) -> dict[str, Any]:
    return {"time": epoch, "open": 2000, "high": 2001, "low": 1999, "close": 2000, "spread": 20}


def test_bars_convert_to_utc_with_the_offset_in_force_at_the_time():
    clock = BrokerClock("America/New_York", 7, 7200)
    summer, winter = broker_epoch(2026, 7, 14, 10), broker_epoch(2026, 11, 10, 10)
    bars = bars_from_rows([row(summer), row(winter)], clock, "M15")
    assert bars[0].open_time == datetime(2026, 7, 14, 7, 0, tzinfo=UTC)  # UTC+3
    assert bars[1].open_time == datetime(2026, 11, 10, 8, 0, tzinfo=UTC)  # UTC+2


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([row(broker_epoch(2026, 11, 10, 10, 7))], "not aligned"),
        ([row(broker_epoch(2026, 11, 10, 10, 15)), row(broker_epoch(2026, 11, 10, 10))],
         "not strictly ascending"),
        ([{**row(broker_epoch(2026, 11, 10, 10)), "high": 1990}], "invalid OHLC"),
    ],
)  # fmt: skip
def test_invalid_history_is_rejected(rows, message):
    with pytest.raises(ValueError, match=message):
        bars_from_rows(rows, BrokerClock("America/New_York", 7, 7200), "M15")
