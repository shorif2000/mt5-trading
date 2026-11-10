"""Fail-closed boundary for the MT5 MCP integration.

The installed community bridge uses a particular local bridge protocol. This module does
not guess that protocol. Verify the installed repository's current source and tool schemas
before implementing a read-only client.
"""

from typing import Protocol

from trading.models import MarketSnapshot


class ReadOnlyMarketDataClient(Protocol):
    def get_snapshot(self, symbols: list[str]) -> MarketSnapshot:
        """Return a verified, timestamped account and market snapshot."""


class MT5MCPClient:
    """Placeholder that deliberately refuses unverified connection attempts."""

    def __init__(self) -> None:
        self._verified = False

    def get_snapshot(self, symbols: list[str]) -> MarketSnapshot:
        del symbols
        raise RuntimeError(
            "MT5 MCP adapter is not implemented. Verify the installed bridge protocol "
            "and use read-only tools. No connection or trading action was attempted."
        )
