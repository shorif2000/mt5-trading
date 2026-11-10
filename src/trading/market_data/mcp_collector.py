"""Collect a raw export from the existing ``mt5-mcp`` server over its documented stdio interface.

This starts the same server Claude Code uses (``uv --directory <repo> run mt5-mcp``) with
``MT5_ENABLE_TRADING=0`` forced, so trading tools are never registered. The server reuses the
already running bridge; no new MT5 connection is created. Only the allowlisted read-only tools
below are ever called, and collection stops if the server advertises any trading tool.

The output is the raw tool responses in the ``mcp-export`` format. All conversion and
validation happens afterwards in ``trading.market_data.mcp_export``.
"""

import asyncio
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

from trading.market_data.mcp_export import EXPORT_FORMAT

READ_ONLY_TOOLS = frozenset(
    {
        "terminal_status",
        "get_account_info",
        "get_symbol_info",
        "get_tick",
        "get_rates",
        "get_positions",
        "get_orders",
    }
)
TRADING_TOOLS = frozenset(
    {
        "place_order",
        "modify_position_sltp",
        "modify_pending_order",
        "close_position",
        "cancel_order",
    }
)
DEFAULT_CALL_TIMEOUT_SECONDS = 60.0


class CollectorError(Exception):
    """Collection could not start or the server is not verifiably read-only."""


class ToolSession(Protocol):
    async def list_tools(self) -> Any: ...

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any: ...


async def verify_read_only(session: ToolSession) -> None:
    listed = await session.list_tools()
    tools = {tool.name: tool for tool in listed.tools}
    exposed_trading = sorted(TRADING_TOOLS & tools.keys())
    if exposed_trading:
        raise CollectorError(f"Server exposes trading tools {exposed_trading}; refusing to collect")
    for name in sorted(READ_ONLY_TOOLS):
        tool = tools.get(name)
        if tool is None:
            raise CollectorError(f"Server does not provide required tool {name!r}")
        if tool.annotations is None or tool.annotations.read_only_hint is not True:
            raise CollectorError(f"Tool {name!r} is not annotated read-only")


async def call_read_only(
    session: ToolSession,
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    timeout: float = DEFAULT_CALL_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Return the tool's structured output, or ``{"tool_error": ...}`` for a failed call."""
    if name not in READ_ONLY_TOOLS:
        raise CollectorError(f"Tool {name!r} is not on the read-only allowlist")
    try:
        result = await asyncio.wait_for(session.call_tool(name, arguments or {}), timeout)
    except TimeoutError:
        return {"tool_error": f"{name} timed out after {timeout:.0f}s"}
    if result.is_error:
        text = " ".join(getattr(item, "text", "") for item in result.content).strip()
        return {"tool_error": text or f"{name} failed without a message"}
    if not isinstance(result.structured_content, dict):
        return {"tool_error": f"{name} returned no structured content"}
    return dict(result.structured_content)


async def collect(
    session: ToolSession,
    *,
    symbols: Sequence[str],
    timeframes: Sequence[str],
    bars: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Collect one export. ``exported_at_utc`` is taken before any market data is read, so a
    candle that completes during collection is still treated as forming."""
    await verify_read_only(session)
    exported_at = (now or datetime.now(UTC)).astimezone(UTC)
    export: dict[str, Any] = {
        "format": EXPORT_FORMAT,
        "exported_at_utc": exported_at.isoformat(),
        "terminal_status": await call_read_only(session, "terminal_status"),
        "account_info": await call_read_only(session, "get_account_info"),
        # Unfiltered: exposure includes every symbol, not only the research instruments.
        "positions": await call_read_only(session, "get_positions"),
        "orders": await call_read_only(session, "get_orders"),
        "symbols": {},
    }
    for symbol in symbols:
        export["symbols"][symbol] = {
            "symbol_info": await call_read_only(session, "get_symbol_info", {"symbol": symbol}),
            "tick": await call_read_only(session, "get_tick", {"symbol": symbol}),
            "rates": {
                timeframe: await call_read_only(
                    session,
                    "get_rates",
                    {"symbol": symbol, "timeframe": timeframe, "count": bars},
                )
                for timeframe in timeframes
            },
        }
    return export


def server_parameters(bridge_repo: Path, uv_executable: str = "uv") -> StdioServerParameters:
    env = {**get_default_environment(), "MT5_ENABLE_TRADING": "0"}
    return StdioServerParameters(
        command=uv_executable,
        args=["--directory", str(bridge_repo), "run", "mt5-mcp"],
        env=env,
    )


async def _collect_from_server(
    params: StdioServerParameters, symbols: Sequence[str], timeframes: Sequence[str], bars: int
) -> dict[str, Any]:
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        return await collect(session, symbols=symbols, timeframes=timeframes, bars=bars)


def collect_to_file(
    output: Path,
    *,
    bridge_repo: Path,
    symbols: Sequence[str],
    timeframes: Sequence[str],
    bars: int,
    uv_executable: str = "uv",
) -> None:
    params = server_parameters(bridge_repo, uv_executable)
    try:
        export = asyncio.run(_collect_from_server(params, symbols, timeframes, bars))
    except CollectorError:
        raise
    except Exception as exc:  # the server process failed to start or the stream broke
        raise CollectorError(f"Could not collect from mt5-mcp: {exc}") from exc
    output.write_text(json.dumps(export, indent=2), encoding="utf-8")
