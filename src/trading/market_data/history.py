"""Read-only download of historical bars and account history through the registered server.

Bars are requested in date-range chunks small enough to stay below the server's 5,000-bar cap,
with one day of overlap (the server converts range limits with the current broker offset,
which differs by an hour across DST changes); duplicates are removed by bar time. Raw responses
are written to a git-ignored ``*.local.json`` file. Nothing here can place or change orders.
"""

import asyncio
import json
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from trading.market_data.mcp_collector import (
    CLAUDE_CONFIG_PATH,
    CollectorError,
    ToolSession,
    call_read_only,
    registered_server,
    server_parameters,
    verify_read_only,
)

CHUNK_DAYS = {"M15": 30, "H1": 150, "H4": 600}
OVERLAP = timedelta(days=1)
HISTORY_CHUNK = timedelta(days=90)


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


async def download_rates(
    session: ToolSession, symbol: str, timeframe: str, start: datetime, end: datetime
) -> dict[str, Any]:
    """All bars in [start, end), plus every chunk problem (a failed or truncated chunk)."""
    step = timedelta(days=CHUNK_DAYS[timeframe])
    rows: dict[int, dict[str, Any]] = {}
    problems: list[str] = []
    offsets: set[object] = set()
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + step, end)
        response = await call_read_only(
            session,
            "get_rates",
            {"symbol": symbol, "timeframe": timeframe, "start": _iso(cursor - OVERLAP),
             "end": _iso(chunk_end)},
        )  # fmt: skip
        if "tool_error" in response:
            problems.append(f"{_iso(cursor)}: {response['tool_error']}")
        elif response.get("truncated") is not False:
            problems.append(f"{_iso(cursor)}: response truncated")
        else:
            offsets.add(response.get("broker_offset_seconds"))
            for row in response.get("rates", []):
                if isinstance(row, dict) and isinstance(row.get("time"), int):
                    rows[row["time"]] = row
        cursor = chunk_end
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "start": _iso(start),
        "end": _iso(end),
        "broker_offsets_seen": sorted(o for o in offsets if isinstance(o, int)),
        "problems": problems,
        "rates": [rows[t] for t in sorted(rows)],
    }


async def download_account_history(
    session: ToolSession, start: datetime, end: datetime, group: str
) -> dict[str, Any]:
    deals: dict[object, dict[str, Any]] = {}
    orders: dict[object, dict[str, Any]] = {}
    problems: list[str] = []
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + HISTORY_CHUNK, end)
        window = {"start": _iso(cursor), "end": _iso(chunk_end), "group": group}
        for tool, store, key in (
            ("get_history_deals", deals, "deals"),
            ("get_history_orders", orders, "orders"),
        ):
            response = await call_read_only(session, tool, window)
            if "tool_error" in response:
                problems.append(f"{tool} {window['start']}: {response['tool_error']}")
                continue
            for row in response.get(key, []):
                if isinstance(row, dict):
                    store[row.get("ticket")] = row
        cursor = chunk_end
    return {
        "group": group,
        "problems": problems,
        "deals": list(deals.values()),
        "orders": list(orders.values()),
    }


async def _download(
    params: StdioServerParameters,
    requests: Sequence[tuple[str, str]],
    start: datetime,
    end: datetime,
    account_group: str | None,
) -> dict[str, Any]:
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        await verify_read_only(session)
        status = await call_read_only(session, "terminal_status")
        terminal = status.get("terminal") if isinstance(status, dict) else None
        if not isinstance(terminal, dict) or terminal.get("connected") is not True:
            raise CollectorError("MT5 terminal is not connected to the broker server")
        result: dict[str, Any] = {"terminal_status": status, "series": []}
        for symbol, timeframe in requests:
            result["series"].append(await download_rates(session, symbol, timeframe, start, end))
        if account_group is not None:
            result["account_history"] = await download_account_history(
                session, start, end, account_group
            )
        return result


def download_history_to_file(
    output: Path,
    *,
    requests: Sequence[tuple[str, str]],
    start: datetime,
    end: datetime,
    account_group: str | None = None,
    config_path: Path = CLAUDE_CONFIG_PATH,
) -> dict[str, Any]:
    if not output.name.endswith(".local.json"):
        raise CollectorError("history output must be a git-ignored *.local.json file")
    params = server_parameters(registered_server(config_path))
    try:
        result = asyncio.run(_download(params, requests, start, end, account_group))
    except CollectorError:
        raise
    except Exception as exc:  # the server process failed to start or the stream broke
        raise CollectorError(f"Could not download history from mt5-mcp: {exc}") from exc
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result), encoding="utf-8")
    return result
