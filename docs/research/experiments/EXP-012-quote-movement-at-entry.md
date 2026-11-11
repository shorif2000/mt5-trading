# EXP-012: quote movement at the modelled entry (historical, descriptive)

- **Status:** registered 2026-11-11, before any result.
- **Question:** how far does the executable quote move in the seconds after the moment the
  backtests assume a market entry, and how far is the backtest's entry model (bar open + bar
  spread) from the first real quote? This bounds the uncertainty in the entry-slippage
  assumption (0, 7 or 40 points). **It does not measure execution slippage:** no order is
  sent.
- **Entries:**
  - every Strategy A signal from the history (`StrategyA`, frozen code) and every Version 1.0
    base-scenario trade;
  - modelled entry from 2025-06-14 to 2026-10-30, the period where bid/ask ticks exist.
- **Data:** read-only MT5 `get_ticks` from 60 s before to 301 s after each entry, cached in a
  git-ignored local file. Times are converted from raw broker time (DST-aware).
- **Measures:**
  - per entry: the first quote's delay and spread;
  - the adverse movement of the executable quote (ask for buys, bid for sells) at +0.5, 1, 2,
    5, 15, 60 and 300 s against the first quote;
  - the worst quote within 5 s;
  - the model entry minus the first quote.
  - The 10th, 25th, 50th, 75th, 90th and 95th percentiles are reported by source (A, Version
    1.0), by session, and for June 2025 separately, where ticks are sparser.
- **Decision rule:** none. It informs the cost assumptions of **future** registered
  experiments only, and changes nothing in EXP-011 (frozen).
- **Limitations:**
  - quotes, not fills;
  - an order's real latency is unknown, so the offsets are illustrative;
  - ticks are sparser in June 2025.
