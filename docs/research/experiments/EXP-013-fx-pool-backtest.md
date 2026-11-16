# EXP-013: EURUSD/GBPUSD/USDJPY event study and backtest (descriptive)

- **Status:** registered 2026-11-16, before any result. Not frozen (descriptive only, like
  EXP-002/004/006); the forward test it feeds into, EXP-014, is frozen.
- **Purpose:** the same per-instrument event study and fixed-parameter backtest already run
  for XAUUSD (EXP-002/003), generalised to EURUSD, GBPUSD and USDJPY, on the same periods
  (Training 2023-24, Validation 2025, 2026 development), same two arms (no cost floor; 0.10R
  cost floor), same cost grid, same news filter (FOMC, CPI, Employment Situation), same fixed-
  risk and compounding ledgers.
- **Specification:** `../strategy-a-fx-pool.md` sections 1-3, 5.
- **Data:** `data/history/fx_pool.local.json` (EURUSD, USDJPY, GBPJPY) and GBPUSD M15 from
  `data/history/xauusd_backtest.local.json`, both sha256-recorded in the report.
- **Decision rule:** none (descriptive, as for EXP-002/004/006). Reported per instrument; no
  pooled historical claim.
- **Limitations:** viewed history (2023-2025 viewed, 2026 development evidence); stop and
  entry slippage are assumptions carried over from gold's evidence (section 3 of the
  specification), not measured for these instruments; one spread value per M15 bar.
