# EXP-006: strategy B (Range mean reversion), setup event study

- **Status:** registered 2026-11-11, before any result.
- **Purpose:** descriptive only. No parameter, rule or arm is chosen from it.
- **Specification:** `../xauusd-strategy-candidates.md`, section B and Amendment 1
  (fixed parameters).
- **Data:** XAUUSD M15 and H1 (`data/history/xauusd_backtest.local.json`, sha256 recorded),
  **2023-01-01 to 2025-01-01 only**.
- **Measures:**
  - setup events by stage (reference level or range, breakout or sweep or visit, retest or
    reclaim, confirmation, invalidation, data incomplete);
  - events per month and by hour (New York);
  - `ATR15` and stop distance (USD and ATR) at the signal;
  - estimated cost C in R, and the share of signals passing the 0.10R cost floor;
  - follow-through: maximum favourable and adverse excursion over the 16 bars after the
    signal, in units of the stop distance, on executable prices.
- **Decision rule:** none. It is reported as observed.
- **Limitations:** viewed history; one spread value per bar; no news filter (it is
  descriptive of all setups).
