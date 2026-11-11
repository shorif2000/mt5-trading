# EXP-009: strategy C (Liquidity sweep and failed breakout), rerun with the complete news calendar

- **Status:** registered 2026-11-11, before any result. This is a rerun of **EXP-005**, whose
  FOMC-only reports stay unchanged as the original record.
- **Only change from EXP-005:** the news filter requires FOMC statements, **CPI and Employment
  Situation** (`config/economic_calendar.yaml` at commit `0c489c1`).
  - Times are verified: CPI and payrolls from each release's embargo statement; FOMC from its
    release page.
  - Rule unchanged: no entries from 30 minutes before to 15 minutes after an event; fail
    closed outside coverage.
- **Everything else is identical to EXP-005:**
  - specification, parameters, arms (no floor; 0.10R floor), periods, cost grid, ledgers,
    margin source, history file;
  - decision rule (registry EXP-005 and programme Amendment 3).
- **The event study is not rerun:** it doesn't use the calendar.
- **Reported:**
  - the same tables as EXP-005;
  - the signals the calendar excludes;
  - a comparison with EXP-005 (FOMC only), in the programme summary addendum.
- **Command:** `uv run python scripts/run_candidate_experiments.py --strategy C
  --backtest-id EXP-009 --skip-study --news-kinds fomc_statement,cpi,employment_situation
  --require-clean`
