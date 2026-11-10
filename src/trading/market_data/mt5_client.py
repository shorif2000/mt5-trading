"""Fail-closed boundary for a direct Python connection to MT5.

The chosen integration (docs/mt5-integration-assessment.md) is a JSON export of read-only
MCP tool responses, validated by ``trading.market_data.mcp_export``. Python deliberately
does not connect to the bridge: its token-authenticated socket also serves ``order_send``.
"""

from typing import Protocol

from trading.models import MarketSnapshot


class ReadOnlyMarketDataClient(Protocol):
    def get_snapshot(self, symbols: list[str]) -> MarketSnapshot:
        """Return a verified, timestamped account and market snapshot."""


class MT5MCPClient:
    """Placeholder that deliberately refuses direct connection attempts."""

    def get_snapshot(self, symbols: list[str]) -> MarketSnapshot:
        del symbols
        raise RuntimeError(
            "Direct MT5 connections are not supported. Export read-only MCP tool responses "
            "and run `mt5-trading ingest`. No connection or trading action was attempted."
        )
