# MT5 Intraday Trading Research

A read-only foundation for researching intraday forex and gold setups with Claude Code.

## Safety status

This project does not place, modify or close orders. It has no live execution implementation.
MT5 data is collected only through an allowlist of eight read-only tools of the existing
`mt5-mcp` server, started with trading forced off. The collector refuses to run if that server
advertises any tool not annotated read-only. The order gateway and approval functions always
raise.

Keep the following controls in place:

- `MT5_ENABLE_TRADING=0`
- MT5 Algo Trading disabled
- Use read-only MCP tools only
- Do not store broker passwords, tokens or account credentials in this repository

## Initial scope

The research universe is EURUSD, GBPUSD, USDJPY and XAUUSD. These exact broker symbol names
were verified against the connected terminal. `XAUUSD.crp` also exists there but is a
conversion-only symbol and is rejected.

The candidate workflow uses H4 for context, H1 for setup identification and M15 for
entry confirmation. The strategy is a research hypothesis, not a proven profitable system.

## Requirements

- Python 3.11 or later
- `uv`
- MetaTrader 5 running and logged in, with
  [`mt5-mcp`](https://github.com/CodeWithBehnam/meta-trader-5-mcp) installed and registered
  for Claude Code at user scope as `mt5`, with trading left disabled:

  ```bash
  claude mcp add --transport stdio --scope user mt5 -- /absolute/path/to/uv --directory /absolute/path/to/meta-trader-5-mcp run mt5-mcp
  ```

  `collect` starts that registered command itself. It accepts only this exact shape (absolute
  `uv` path, absolute repository path, no `MT5_ENABLE_TRADING=1`) and takes no command or path
  from the command line.

## Setup

```bash
uv sync
```

No `.env` file or credentials are needed. See `docs/mt5-integration-assessment.md` for the
integration design, validation rules and limitations.

## Run the diagnostic

```bash
uv run mt5-trading collect     # raw read-only tool responses -> data/mcp_export.local.json
uv run mt5-trading ingest --export data/mcp_export.local.json   # validate -> data/snapshot.local.json
uv run mt5-trading diagnose --snapshot data/snapshot.local.json
```

`*.local.json` files can contain real account data and are git-ignored anywhere in the
repository. `collect` replaces the account login, name, server and company with `REDACTED`
before writing. `ingest` rejects stale, incomplete, disconnected or timezone-ambiguous data and
lists every reason. Broker times are converted to UTC with the daylight-saving rule in force at
each moment. The default is New York time + 7 h, overridable with
`--broker-timezone/--broker-shift-hours`.

`data/example_mcp_export.json` is an entirely synthetic example export.
`data/sample_snapshot.json` is an empty illustrative template.

## XAUUSD backtest (research only)

The approved XAUUSD M15 trend pullback strategy, Version 1.0
(`docs/strategy-xauusd-trend-pullback.md`), can be backtested offline on a GBP 100 paper
ledger. History and broker margin come from MT5 read-only; nothing is sent to the market.

```bash
uv run mt5-trading collect-history                  # read-only bars, git-ignored local file
uv run mt5-trading slippage-evidence                # stop-loss slippage from local history
uv run mt5-trading backtest                         # every cost scenario in config/backtest.yaml
```

Costs are set in `config/backtest.yaml`. Stop-exit slippage comes from the account's observed
stop-loss fills. Entry slippage is unknown, so the backtest runs labelled scenarios rather than
assuming a value; take profits fill at the target.

## Validate

```bash
uv run pytest
uv run ruff check .
uv run mypy src
```

## Market calendar

`config/market_sessions.yaml` defines when each market is scheduled to be open (New York time).
Missing candles are accepted only while a market is closed:
- **Broker closures:** add holidays, early closes and late opens under `closures` from the
  broker's published notices with `status: confirmed`, or `ingest` will reject the gap.
- **Exchange holidays:** `config/exchange_holidays.yaml` holds exchange holidays (US, UK,
  Australia, India automated; Japan, Hong Kong, Singapore by hand) as reference only. A weekly
  GitHub Actions workflow proposes updates as a pull request; nothing is fetched at runtime.

```bash
uv run mt5-trading calendar      # last update and coverage of the local calendar
uv run mt5-calendar-update --report report.md   # what the weekly workflow runs
```

## Project principles

1. Market data must be timestamped and checked for freshness.
2. Strategy calculations must be deterministic Python, not free-form model reasoning.
3. The risk engine must reject incomplete or unsafe proposals.
4. A proposal is not an order.
5. No execution code is included in this version.
6. Never use the live account to test order placement.
