"""The collector must only ever call allowlisted read-only tools and must fail closed."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from trading.market_data.mcp_collector import (
    READ_ONLY_TOOLS,
    CollectorError,
    call_read_only,
    collect,
    redact_account,
    registered_server,
    server_parameters,
)


def tool(
    name: str, read_only: bool | None = True, destructive: bool | None = None
) -> SimpleNamespace:
    annotations = (
        None
        if read_only is None
        else SimpleNamespace(read_only_hint=read_only, destructive_hint=destructive)
    )
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


def test_refuses_unknown_tool_not_annotated_read_only():
    session = FakeSession([*read_only_tools(), tool("send_market_order", read_only=False)])
    with pytest.raises(CollectorError, match="send_market_order"):
        run_collect(session)
    assert session.calls == []


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


@pytest.mark.parametrize(
    "unapproved",
    [
        tool("export_history"),  # unknown but read-only: allowed to exist, never called
    ],
)
def test_unknown_read_only_tool_is_listed_but_never_called(unapproved):
    session = FakeSession([*read_only_tools(), unapproved])
    run_collect(session)
    assert unapproved.name not in {name for name, _ in session.calls}


@pytest.mark.parametrize(
    "bad_tool",
    [
        tool("get_ticks", read_only=None),  # annotation missing
        tool("get_ticks", read_only=False),  # annotation false
        tool("get_ticks", read_only=True, destructive=True),  # contradictory metadata
        SimpleNamespace(name="get_ticks", annotations=SimpleNamespace()),  # no hint at all
    ],
    ids=["missing", "false", "destructive", "no-hint"],
)
def test_refuses_any_tool_without_trustworthy_read_only_annotation(bad_tool):
    session = FakeSession([*read_only_tools(), bad_tool])
    with pytest.raises(CollectorError, match="not annotated read-only"):
        run_collect(session)
    assert session.calls == []


def test_account_identifiers_are_redacted_before_export():
    info = {"login": 123, "name": "A", "server": "S", "company": "C", "balance": 5.0}
    assert redact_account(info) == {
        "login": "REDACTED",
        "name": "REDACTED",
        "server": "REDACTED",
        "company": "REDACTED",
        "balance": 5.0,
    }
    assert redact_account({"tool_error": "x"}) == {"tool_error": "x"}


# --- registered server ------------------------------------------------------------------


def write_config(tmp_path: Path, entry: dict[str, Any] | None) -> Path:
    path = tmp_path / "claude.json"
    servers = {} if entry is None else {"mt5": entry}
    path.write_text(json.dumps({"mcpServers": servers, "unrelated": {"secret": "x"}}))
    return path


def registration(repo: Path, **overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "type": "stdio",
        "command": "/opt/tools/uv",
        "args": ["--directory", str(repo), "run", "mt5-mcp"],
        "env": {},
    }
    entry.update(overrides)
    return entry


def test_server_comes_from_registration_with_trading_forced_off(tmp_path):
    server = registered_server(write_config(tmp_path, registration(tmp_path)))
    params = server_parameters(server)

    assert params.command == "/opt/tools/uv"
    assert params.args == ["--directory", str(tmp_path), "run", "mt5-mcp"]
    assert params.env is not None and params.env["MT5_ENABLE_TRADING"] == "0"
    assert not any(key.startswith("MT5_") and key != "MT5_ENABLE_TRADING" for key in params.env)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"type": "http"}, "not a stdio server"),
        ({"env": {"MT5_ENABLE_TRADING": "1"}}, "trading enabled"),
        ({"command": "uv"}, "absolute path to uv"),
        ({"command": "/bin/sh"}, "absolute path to uv"),
        ({"args": ["--directory", "relative/repo", "run", "mt5-mcp"]}, "existing absolute"),
        ({"args": ["--directory", "/no/such/repo", "run", "mt5-mcp"]}, "existing absolute"),
        ({"args": ["run", "--with", "evil", "mt5-mcp"]}, "args must be exactly"),
        ({"args": ["--directory", "/tmp", "run", "mt5-mcp", "--http"]}, "args must be exactly"),
    ],
)
def test_unexpected_registration_is_refused(tmp_path, overrides, message):
    config = write_config(tmp_path, registration(tmp_path, **overrides))
    with pytest.raises(CollectorError, match=message):
        registered_server(config)


def test_missing_registration_is_refused(tmp_path):
    with pytest.raises(CollectorError, match="No user-scope MCP server"):
        registered_server(write_config(tmp_path, None))


def test_unreadable_registration_is_refused(tmp_path):
    with pytest.raises(CollectorError, match="Cannot read MCP registration"):
        registered_server(tmp_path / "missing.json")
