# EXP-014: Strategy A forward test, pooled with EXP-011

- **Status:** registered 2026-11-16, before any forward data for these instruments exists.
  Frozen: see `../strategy-a-fx-pool-freeze.json`.
- **Hypothesis:** Strategy A, completely unchanged, has positive gross and net expectancy
  across XAUUSD (EXP-011), EURUSD, GBPUSD and USDJPY pooled, on data none of them was designed
  on.
- **Specification and decision rule:** `../strategy-a-fx-pool.md` (frozen), extending
  `../strategy-a-forward-test.md` section 3 rather than replacing it.
- **Forward data:** signal bars closing from 2026-11-15 23:00 UTC onwards (the same moment as
  EXP-011's own forward start), collected read-only.
- **Arms:** no cost floor; 0.10R cost floor. Each evaluated separately at 97.5%, on the pooled
  sample across all four instruments.
- **Evaluation:** ready once the pooled sample has at least 100 events and 26 weeks; closed as
  insufficient data on 2028-11-15, the same deadline as EXP-011.
- **Pooling-specific criterion:** net R positive in at least 3 of the 4 instruments
  individually, on top of EXP-011's six criteria, computed on the pooled sample.
- **Outcome language:** supported, negative or inconclusive, exactly as EXP-011; "supported"
  is evidence, not a trading recommendation.
- **EXP-011 is not superseded by this experiment:** its own XAUUSD-only stream, freeze and
  reports continue independently; this experiment pools it with three more instruments for a
  separate, broader question.
- **Limitations:** entry and stop-exit slippage are carried-over assumptions for the FX
  instruments, not measured for them; the calendar must be kept current; four instruments
  sharing one calendar event (e.g. an FOMC statement) are not fully independent observations.
