# EXP-005: strategy C (Liquidity sweep and failed breakout), fixed-parameter backtest

- **Status:** registered 2026-11-11, before any result.
- **Hypothesis:** strategy C, as specified, has positive gross and net expectancy on XAUUSD
  M15 after realistic costs.
- **Specification:** `../xauusd-strategy-candidates.md`, section C, common definitions and
  Amendment 1; programme Amendment 1 (A1.3, A1.4). All parameters fixed. Nothing is tuned.
- **Data:** XAUUSD M15 and H1 and GBPUSD M15 (`data/history/xauusd_backtest.local.json`,
  sha256 recorded); official economic calendar (`config/economic_calendar.yaml`).
- **Periods:**
  - Training 2023–2024: development;
  - Validation 2025: one run;
  - 2026-01 to 2026-10: development evidence.
  - 2026-11-01 onwards is excluded. The forward hold-out starts 2026-11-16.
- **Arms (fixed before running):**
  - no cost floor, news filter on;
  - 0.10R cost floor, news filter on.
  - Each also runs with the news filter off, only to count what the calendar excludes.
- **Costs:**
  - the existing grid: entry slippage of 0, 7 and 40 points (scenarios); stop slippage at the
    p50, p90 and p95 percentiles (measured);
  - spread from bars;
  - take profit 0, commission £0, swap 0 (none held overnight);
  - margin from MT5 `calc_margin` (read-only), as in Version 1.0.
- **Risk:**
  - 2% maximum through the existing risk engine;
  - reject when the 0.01-lot minimum exceeds 2%.
- **Ledgers:**
  - fixed risk: each trade sized at 2% of a constant £1,000;
  - compounding: 2% of the running balance, £1,000 per period.
- **Events:** one per specification event definition (one trade per event).
- **Reported:**
  - signals, events, executed trades;
  - every rejection reason (strategy, filters, news, cost floor, risk, margin, position
    open);
  - gross and net results, costs, drawdown;
  - both ledgers.
- **Decision rule (pre-registered).** Base scenario, fixed-risk ledger, news filter on. Each
  arm is classified as follows:
  - **Insufficient data:** fewer than 100 events in a period.
  - **Candidate for the forward hold-out only:** all of the following hold. It is never
    called "profitable".
    - gross and net expectancy > 0 in every period;
    - the pooled 2023–2026 95% bootstrap interval of net R per trade is above 0;
    - the sum of R stays > 0 without the 10 best trades;
    - net expectancy > 0 in the stop-p90-proxy (40-point) entry scenario;
    - net expectancy > 0 in at least two of three `ADR`-ratio volatility terciles.
  - **Assumption-dependent:** positive only with zero entry slippage.
  - **Negative:** the pooled net 95% interval is below 0.
  - **Inconclusive:** anything else.
- **Limitations:**
  - viewed history; 2026 is development evidence;
  - one spread value per bar; stop-first ordering within a bar;
  - partial news calendar;
  - entry slippage unknown.
