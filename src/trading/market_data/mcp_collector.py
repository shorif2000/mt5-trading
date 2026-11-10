"""Collect a raw export from the existing ``mt5-mcp`` server over its documented stdio interface.

This starts the server registered for Claude Code as ``mt5`` in ``~/.claude.json``
(``<uv> --directory <repo> run mt5-mcp``), read from that registration rather than from user
input, with ``MT5_ENABLE_TRADING=0`` forced, so trading tools are never registered. The server
reuses the already running bridge; no new MT5 connection is created. Only the allowlisted
read-only tools below are ever called, and collection stops if the server advertises any tool
not annotated read-only.

The output is the raw tool responses in the ``mcp-export`` format. All conversion and
validation happens afterwards in ``trading.market_data.mcp_export``.
"""

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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
        # Broker margin calculation (MT5 order_calc_margin): computes only, sends nothing.
        "calc_margin",
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
CLAUDE_CONFIG_PATH = Path.home() / ".claude.json"
REGISTERED_SERVER_NAME = "mt5"
# Account fields that identify the account holder or broker server. Replaced before the raw
# export is written; validation only needs them to be non-empty strings.
REDACTED_ACCOUNT_FIELDS = ("login", "name", "server", "company")
REDACTED = "REDACTED"


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
    missing = sorted(READ_ONLY_TOOLS - tools.keys())
    if missing:
        raise CollectorError(f"Server does not provide required tools {missing}")
    # Fail closed on any advertised tool that is not declared read-only, including trading
    # tools under names this module does not know about, and on contradictory annotations.
    not_read_only = sorted(name for name, tool in tools.items() if not _is_read_only(tool))
    if not_read_only:
        raise CollectorError(
            f"Server advertises tools not annotated read-only {not_read_only}; refusing to collect"
        )


def _is_read_only(tool: Any) -> bool:
    annotations = getattr(tool, "annotations", None)
    if annotations is None:
        return False
    if getattr(annotations, "read_only_hint", None) is not True:
        return False
    # A tool cannot be both read-only and destructive; treat that as untrustworthy metadata.
    return getattr(annotations, "destructive_hint", None) is not True


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


def redact_account(info: Mapping[str, Any]) -> dict[str, Any]:
    """Replace account-identifying fields; a failed call (``tool_error``) is kept as is."""
    if "tool_error" in info:
        return dict(info)
    return {
        key: REDACTED if key in REDACTED_ACCOUNT_FIELDS else value for key, value in info.items()
    }


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
        "account_info": redact_account(await call_read_only(session, "get_account_info")),
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


@dataclass(frozen=True)
class RegisteredServer:
    uv_executable: Path
    bridge_repo: Path


def registered_server(
    config_path: Path = CLAUDE_CONFIG_PATH, name: str = REGISTERED_SERVER_NAME
) -> RegisteredServer:
    """Read the user-scope ``mt5`` MCP registration and accept only the expected exact shape:
    ``<absolute uv> --directory <absolute repo> run mt5-mcp`` over stdio, with trading not
    enabled. Only that registration's values are used; nothing else in the file is read out."""
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CollectorError(f"Cannot read MCP registration from {config_path}: {exc}") from exc
    servers = config.get("mcpServers") if isinstance(config, dict) else None
    entry = servers.get(name) if isinstance(servers, dict) else None
    if not isinstance(entry, dict):
        raise CollectorError(f"No user-scope MCP server {name!r} registered in {config_path}")
    if entry.get("type", "stdio") != "stdio":
        raise CollectorError(f"MCP server {name!r} is not a stdio server")
    env = entry.get("env") or {}
    if not isinstance(env, dict) or env.get("MT5_ENABLE_TRADING", "0") != "0":
        raise CollectorError(f"MCP server {name!r} is registered with trading enabled; refusing")

    command, args = entry.get("command"), entry.get("args")
    if not isinstance(command, str) or not isinstance(args, list):
        raise CollectorError(f"MCP server {name!r} has no command or args")
    uv_executable = Path(command)
    if not uv_executable.is_absolute() or uv_executable.name != "uv":
        raise CollectorError(f"MCP server {name!r} command must be an absolute path to uv")
    if len(args) != 4 or args[0] != "--directory" or args[2:] != ["run", "mt5-mcp"]:
        raise CollectorError(
            f"MCP server {name!r} args must be exactly ['--directory', <repo>, 'run', 'mt5-mcp']"
        )
    bridge_repo = Path(args[1]) if isinstance(args[1], str) else None
    if bridge_repo is None or not bridge_repo.is_absolute() or not bridge_repo.is_dir():
        raise CollectorError(f"MCP server {name!r} repository must be an existing absolute path")
    return RegisteredServer(uv_executable=uv_executable, bridge_repo=bridge_repo)


def server_parameters(server: RegisteredServer) -> StdioServerParameters:
    # Minimal default environment (no inherited MT5_* settings) with trading forced off.
    env = {**get_default_environment(), "MT5_ENABLE_TRADING": "0"}
    return StdioServerParameters(
        command=str(server.uv_executable),
        args=["--directory", str(server.bridge_repo), "run", "mt5-mcp"],
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
    symbols: Sequence[str],
    timeframes: Sequence[str],
    bars: int,
    config_path: Path = CLAUDE_CONFIG_PATH,
) -> None:
    params = server_parameters(registered_server(config_path))
    try:
        export = asyncio.run(_collect_from_server(params, symbols, timeframes, bars))
    except CollectorError:
        raise
    except Exception as exc:  # the server process failed to start or the stream broke
        raise CollectorError(f"Could not collect from mt5-mcp: {exc}") from exc
    output.write_text(json.dumps(export, indent=2), encoding="utf-8")


async def request_margin(
    session: ToolSession, *, symbol: str, side: str, volume: float, price: float | None = None
) -> dict[str, Any]:
    """Ask MT5 for the margin of one proposed position. Read-only: calc_margin only."""
    if side not in ("BUY", "SELL"):
        raise CollectorError(f"side must be BUY or SELL, got {side!r}")
    await verify_read_only(session)
    arguments: dict[str, Any] = {"symbol": symbol, "side": side, "volume": volume}
    if price is not None:
        arguments["price"] = price
    return await call_read_only(session, "calc_margin", arguments)


async def _margin_from_server(
    params: StdioServerParameters, symbol: str, side: str, volume: float, price: float | None
) -> dict[str, Any]:
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        return await request_margin(session, symbol=symbol, side=side, volume=volume, price=price)


def margin_from_server(
    *,
    symbol: str,
    side: str,
    volume: float,
    price: float | None = None,
    config_path: Path = CLAUDE_CONFIG_PATH,
) -> dict[str, Any]:
    params = server_parameters(registered_server(config_path))
    try:
        return asyncio.run(_margin_from_server(params, symbol, side, volume, price))
    except CollectorError:
        raise
    except Exception as exc:  # the server process failed to start or the stream broke
        raise CollectorError(f"Could not request margin from mt5-mcp: {exc}") from exc
