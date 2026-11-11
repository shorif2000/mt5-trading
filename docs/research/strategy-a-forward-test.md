# Strategy A: frozen forward test (EXP-011)

**Status:** frozen on 2026-11-11, before any forward data exists. Checksums of every file
that decides a signal, its filters, sizing, costs and evaluation are in
`strategy-a-freeze.json`. The observer and the monitor refuse to run if any of them changes.
A changed rule is a **new** experiment with a new id. This one is never edited.

Research only. **No orders are placed.** Strategy A is observed, not traded.

## 1. What is frozen

| Element | Frozen value |
|---|---|
| Strategy | A, session breakout and retest: `xauusd-strategy-candidates.md`, section A, common definitions and Amendment 1 (including the chronological day-priority rule) |
| Code | `src/trading/research/candidates.py` (`StrategyA`), `levels.py`, `candidate_engine.py`, the Version 1.0 engine, risk sizing and margin, and indicators (checksums in the freeze record) |
| Arms | (1) no cost floor; (2) 0.10R cost floor, where estimated cost C = entry-bar spread + 7 + 40 points (programme A1.3) |
| News filter | FOMC statements, CPI and Employment Situation from `config/economic_calendar.yaml`. No entries from 30 minutes before to 15 minutes after an event. Fail closed outside coverage. |
| Risk | 2% of a constant £1,000 per trade (fixed-risk ledger; compounding ledger also reported). Reject when the 0.01-lot minimum exceeds 2%. |
| Exits | Stop, 2R target, 16:45 New York forced close; no overnight positions |
| Forward data | Signal bars closing from **2026-11-15 23:00 UTC** (trading day 2026-11-16) onwards, completed bars only, collected read-only |

## 2. Costs: measured or assumed

| Cost | Status in the forward evaluation |
|---|---|
| Spread | **Measured** (bar spread from MT5 history) |
| Stop-loss slippage | **Measured** distribution of the account's stop fills; p90 = 40 points in the base |
| Entry and market-exit slippage | **Assumed**: 7 points in the base, 40 points in the stress scenario. Forward quote observations (section 4) describe how quotes move after the entry moment. They are not execution slippage, and they do not change these assumptions within EXP-011. |
| Take-profit slippage | Measured: 0 |
| Commission | Measured: £0 |
| Swap | 0 (no overnight positions) |

## 3. Pre-registered decision rule

Each arm is evaluated separately: base cost scenario, fixed-risk ledger, news filter on.

- **When:** at the first weekly monitoring report on or after the date when the arm has **at
  least 100 forward events** (signals, one per setup event) **and at least 26 weeks** have
  passed since the forward start.
  - Until then, every report is descriptive only and labelled "NOT READY".
  - If an arm has not qualified by **2028-11-15**, it is closed as **insufficient data**.
- **Criteria:** all must hold for the result to be "supported on forward data":
  1. mean gross R per trade > 0;
  2. mean net R per trade > 0;
  3. the lower bound of the **97.5%** bootstrap interval of net R is above 0 (97.5%, not
     95%, because two arms are evaluated);
  4. the sum of net R stays above 0 without the 10 best trades;
  5. mean net R > 0 in the 40-point entry-slippage stress scenario;
  6. mean net R > 0 in at least two of three `ADR`-ratio volatility terciles. The tercile
     cut-offs are fixed numbers in the freeze record, from 2023–2024 signals.
- **Outcomes:**
  - **Supported:** all six criteria hold.
  - **Negative:** the upper bound of the interval is below 0.
  - **Inconclusive:** anything else.
- **"Supported" is not a recommendation to trade.** Any execution would need a separate
  explicit project decision, independent risk controls, a human approval mechanism and a demo
  execution study, as `CLAUDE.md` requires.

## 4. Observation procedure

- **Collection:** `uv run python scripts/forward_observe.py`, run at least daily (every 15
  minutes from cron is suitable). It is read-only and safe to repeat.
  - Bars are stored in `data/forward/bars.local.json` (git-ignored).
  - Signals are logged in `data/forward/strategy_a_signals.jsonl`, committed weekly.
  - The bar that is still forming is never used.
- **Quote observations:** for each signal, bid/ask ticks from 60 s before to 301 s after the
  modelled entry moment (the open of the bar after the signal bar).
  - Recorded: the first real quote, the executable quote (ask for a buy, bid for a sell) at
    +0.5 s, 1 s, 2 s, 5 s, 15 s, 60 s and 300 s, the spreads, the worst quote within 5 s, and
    the gap between the backtest's entry model (bar open + spread) and the first real quote.
  - Logged in `data/forward/strategy_a_quotes.jsonl`.
- **Monitoring:** `uv run python scripts/strategy_a_monitor.py`, weekly, writes a new report
  to `reports/forward/`. The report covers:
  - readiness, events, rejections and their reasons;
  - spread and cost ÷ stop distance, and the stop-distance distribution;
  - gross and net results with confidence intervals, by year and by session;
  - quote evidence, data completeness and calendar coverage.
  - It contains **no buy or sell recommendation**.
- **Calendar upkeep:** rebuild the economic calendar regularly (`scripts/save_bls_pages.sh`,
  `scripts/download_bls_releases.sh`, `scripts/build_economic_calendar.py`). After the last
  verified publication, only scheduled dates apply. A future FOMC meeting without a published
  time blocks its whole New York day.

## 5. Not allowed

- **Rule changes:** changing parameters, filters, sessions, costs or the decision rule after the
  freeze.
- **Selective reporting:** dropping weeks, signals or trades from the forward record. The
  observer only appends; disagreements are logged as inconsistencies.
- **Mixing evidence:** using 2026-11-01 to 2026-11-13 data, or any pre-forward data, as forward
  evidence.
- **Executing trades:** placing, modifying or closing orders as part of this experiment.
