# MT5 Intraday Trading Research

A read-only foundation for researching intraday forex and gold setups with Claude Code.

## Safety status

This project does not place, modify or close orders. It has no live execution implementation.
The MT5 adapter is deliberately a fail-closed interface until the installed bridge protocol
and its exact read-only tools have been verified.

Keep the following controls in place:

- `MT5_ENABLE_TRADING=0`
- MT5 Algo Trading disabled
- Use read-only MCP tools only
- Do not store broker passwords, tokens or account credentials in this repository

## Initial scope

The intended research universe is EURUSD, GBPUSD, USDJPY and XAUUSD. The exact broker
symbol names must be confirmed from the connected terminal before use.

The candidate workflow uses H4 for context, H1 for setup identification and M15 for
entry confirmation. The strategy is a research hypothesis, not a proven profitable system.

## Requirements

- Python 3.11 or later
- `uv`

## Setup

```bash
uv sync
cp .env.example .env
```

The application reads MT5 data only through the read-only tools of the existing `mt5-mcp`
server, started with trading forced off. See `docs/mt5-integration-assessment.md`.

## Run the diagnostic

```bash
uv run mt5-trading collect     # raw read-only tool responses -> data/mcp_export.local.json
uv run mt5-trading ingest --export data/mcp_export.local.json   # validate -> data/snapshot.local.json
uv run mt5-trading diagnose --snapshot data/snapshot.local.json
```

`*.local.json` files contain real account data and are git-ignored. `ingest` rejects stale,
incomplete, disconnected or timezone-ambiguous data and lists every reason.
`data/sample_snapshot.json` is an empty illustrative template.

## Validate

```bash
uv run pytest
uv run ruff check .
uv run mypy src
```

## Market calendar

`config/market_sessions.yaml` defines when each market is scheduled to be open (New York time).
Missing candles are accepted only while a market is closed. Holidays and early closes are not
shipped: add each one under `closures` from the broker's published schedule, or `ingest` will
reject the gap.

## Project principles

1. Market data must be timestamped and checked for freshness.
2. Strategy calculations must be deterministic Python, not free-form model reasoning.
3. The risk engine must reject incomplete or unsafe proposals.
4. A proposal is not an order.
5. No execution code is included in this version.
6. Never use the live account to test order placement.
