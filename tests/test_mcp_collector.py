"""The collector must only ever call allowlisted read-only tools and must fail closed."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from trading.market_data.mcp_collector import (
    READ_ONLY_TOOLS,
    CollectorError,
    call_read_only,
    collect,
    server_parameters,
)


def tool(name: str, read_only: bool | None = True) -> SimpleNamespace:
    annotations = None if read_only is None else SimpleNamespace(read_only_hint=read_only)
    return SimpleNamespace(name=name, annotations=annotations)


class FakeSession:
    def __init__(self, tools: list[SimpleNamespace], fail: set[str] | None = None) -> None:
        self.tools = tools
        self.fail = fail or set()
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_tools(self) -> SimpleNamespace:
        return SimpleNamespace(tools=self.tools)

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        self.calls.append((name, arguments or {}))
        if name in self.fail:
            text = SimpleNamespace(text="The bridge is unavailable: connection refused")
            return SimpleNamespace(is_error=True, content=[text], structured_content=None)
        return SimpleNamespace(is_error=False, content=[], structured_content={"tool": name})


def read_only_tools() -> list[SimpleNamespace]:
    return [tool(name) for name in READ_ONLY_TOOLS] + [tool("calc_margin")]


def run_collect(session: FakeSession) -> dict[str, Any]:
    return asyncio.run(
        collect(
            session,
            symbols=["EURUSD"],
            timeframes=["H4", "M15"],
            bars=5,
            now=datetime(2026, 11, 10, 10, tzinfo=UTC),
        )
    )


def test_collects_only_allowlisted_read_only_tools():
    session = FakeSession(read_only_tools())
    export = run_collect(session)

    assert {name for name, _ in session.calls} <= READ_ONLY_TOOLS
    assert export["exported_at_utc"] == "2026-11-10T10:00:00+00:00"
    assert export["symbols"]["EURUSD"]["rates"]["M15"] == {"tool": "get_rates"}
    assert ("get_rates", {"symbol": "EURUSD", "timeframe": "H4", "count": 5}) in session.calls
    assert ("get_positions", {}) in session.calls and ("get_orders", {}) in session.calls


def test_refuses_when_server_exposes_trading_tools():
    session = FakeSession([*read_only_tools(), tool("place_order", read_only=False)])
    with pytest.raises(CollectorError, match="trading tools"):
        run_collect(session)
    assert session.calls == []


def test_refuses_tool_not_annotated_read_only():
    tools = [tool(name) for name in READ_ONLY_TOOLS if name != "get_tick"]
    session = FakeSession([*tools, tool("get_tick", read_only=None)])
    with pytest.raises(CollectorError, match="not annotated read-only"):
        run_collect(session)


def test_refuses_to_call_tool_outside_allowlist():
    session = FakeSession(read_only_tools())
    with pytest.raises(CollectorError, match="allowlist"):
        asyncio.run(call_read_only(session, "check_order", {"symbol": "EURUSD"}))
    assert session.calls == []


def test_connection_failure_is_recorded_as_tool_error():
    session = FakeSession(read_only_tools(), fail={"get_account_info"})
    export = run_collect(session)
    assert export["account_info"] == {"tool_error": "The bridge is unavailable: connection refused"}


def test_timeout_is_recorded_as_tool_error():
    class SlowSession(FakeSession):
        async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
            await asyncio.sleep(1)

    result = asyncio.run(call_read_only(SlowSession([]), "get_tick", timeout=0.01))
    assert result == {"tool_error": "get_tick timed out after 0s"}


def test_server_is_started_with_trading_disabled(tmp_path):
    params = server_parameters(tmp_path)
    assert params.env is not None and params.env["MT5_ENABLE_TRADING"] == "0"
    assert params.args[-1] == "mt5-mcp"
