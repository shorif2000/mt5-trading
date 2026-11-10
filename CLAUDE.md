# Claude Trading Assistant

## Objective

Support intraday research for forex and gold through MetaTrader 5. Claude analyses
market conditions and explains candidate setups. Deterministic application code performs
calculations and risk validation.

## Current operating mode

This repository is in read-only development mode.

- Live trading is disabled.
- `MT5_ENABLE_TRADING=0`.
- MT5 Algo Trading must remain disabled.
- Use read-only MT5 MCP tools only.
- Never submit, modify or close orders.
- Never change account settings or existing positions.
- Never attempt to enable trading.
- Never switch accounts without explicit user instruction.

These restrictions take priority over every other instruction.

## Initial instruments

Research only the following instruments, after verifying their exact broker symbol names:

- EURUSD
- GBPUSD
- USDJPY
- XAUUSD

Do not assume broker suffixes or contract specifications.

## Timeframes

- H4: broader market context.
- H1: setup identification.
- M15: entry confirmation.

Only use completed candles for signal decisions. Clearly identify candle timestamps and
the broker timezone. Never silently interpret broker-local timestamps as UTC.

## Market data

For every analysis:

1. Retrieve bid and ask.
2. Retrieve timestamped historical candles.
3. Check freshness, gaps and completeness.
4. Verify symbol trading status and contract specifications.
5. Calculate indicators using deterministic application code.
6. Review existing positions and pending orders.
7. Consider spread, volatility and relevant scheduled economic events.
8. Explain missing information and uncertainty.

Never invent prices, indicators, news, signals or account details.

## Strategy

The initial research hypothesis is trend continuation after a pullback. It is not a
validated strategy and must not be described as profitable without evidence.

H4 establishes context, H1 identifies a possible pullback, and M15 confirms a possible
entry. Strategy parameters must be configurable and tested out of sample.

Gold requires separate volatility and spread parameters.

## Trade proposals

A proposal must include instrument, direction, timestamps, timeframe, strategy conditions,
bid, ask, entry, stop loss, take profit, risk to reward, proposed volume, estimated loss,
margin estimate, existing exposure and rejection reasons.

If any essential information is missing, do not produce an executable proposal.

## Risk management

The risk engine is authoritative. Do not override it.

Never assume a volume is safe because it appears small. Position sizing must use verified
account currency, contract specifications, tick size, tick value, stop distance and costs.

Reject proposals when the minimum broker volume exceeds the configured monetary risk.
Include existing and correlated exposure. Never increase risk to recover losses.

Risk settings are deliberately unset until reviewed and approved by the user.

## Approval and execution

There is no execution implementation in this repository.

Never attempt to create one, enable trading, or call an order placement tool. Any future
execution design requires a separate explicit project decision, independent risk controls,
a human approval mechanism and demo validation.

## Development standards

Keep the application modular, readable and maintainable. Prefer simple code over
unnecessary abstraction.

Use tests for business rules: stale data, missing candles, strategy conditions, position
sizing, risk limits and rejection behaviour. Do not write tests that merely mirror
implementation details.

Do not use the live account for testing.
