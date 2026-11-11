# EXP-001: break-even exits on the Version 1.0 entries

- **Status:** registered 2026-11-11, before any result.
- **Hypothesis:** moving the stop to break-even (at 0.5R, 0.75R or 1.0R, or to break-even plus
  costs at 1.0R) changes Version 1.0's gross expectancy.
  - Expected: it redistributes outcomes (more small exits, fewer full losses and full
    targets) without creating an edge.
- **Specification:**
  - `../xauusd-research-programme.md`, section 3 and Amendment 1 (A1.2);
  - Version 1.0 strategy unchanged (`../../strategy-xauusd-trend-pullback.md`).
- **Data:**
  - Version 1.0 run `20261110T222100Z_7f525aace4`: its base-scenario trade list from the
    manifest;
  - its history file `data/history/xauusd_backtest.local.json`, sha256 checked against the
    manifest;
  - tick data (read-only) for the sensitivity analysis only.
- **Periods:** Training 2023–2024 and Validation 2025 (both viewed); 2026-01 to 2026-10
  (development evidence).
- **Variants:**
  - BE-0 (control);
  - BE-0.5, BE-0.75 and BE-1.0: stop to the entry fill;
  - BE-1.0+C: stop to entry fill + entry-bar spread + scenario entry slippage + scenario stop
    slippage.
- **Primary method:** M15 bar-close management (A1.2).
- **Sensitivity:**
  - intrabar management, under both trigger-bar orderings;
  - tick-resolved from 2025-06-13.
- **Costs:**
  - spread measured from bars;
  - stop slippage from the measured percentiles (p50, p90, p95);
  - entry and market-exit slippage are scenarios (0, 7 and 40 points);
  - take profit 0 (measured);
  - commission £0 (measured);
  - swap 0 (positions never held overnight).
- **Ledgers:**
  - fixed risk (R; × £20);
  - compounding (Version 1.0 volumes, £1,000 per period).
- **Events:** distinct Version 1.0 pullback events (the strategy's `pullback_event_start`).
- **Metrics:**
  - net and gross expectancy;
  - profit factor, win rate, average win and loss;
  - maximum drawdown;
  - exit mix;
  - break-even exits that later reached the original target;
  - extra spread and slippage;
  - ambiguous trigger bars.
- **Reconciliation gate:** in the base scenario, BE-0 must reproduce every Version 1.0 trade
  (exit time, exit reason, net GBP) exactly. No other result is accepted otherwise.
- **Decision rule (pre-registered, section 3.4):**
  - No variant is selected from 2023–2026.
  - A variant is only "worth forward testing" if its fixed-risk **gross** expectancy beats
    BE-0 in all three periods, without relying on the zero-entry-slippage scenario.
  - Because Version 1.0 has no gross edge (diagnostic review), no variant is adopted
    whatever the result.
- **Limitations:**
  - fixed entry list, so trades skipped by Version 1.0 while a position was open stay
    skipped;
  - non-base scenarios replay the base list without re-sizing;
  - one spread value per M15 bar.
- **Comparisons so far in the programme:** Version 1.0, Version 1.1, the diagnostic buckets.
