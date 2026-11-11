# EXP-011: Strategy A forward test (frozen)

- **Status:** registered 2026-11-11, before any forward data exists. Frozen: see
  `../strategy-a-freeze.json`.
- **Hypothesis:** Strategy A (session breakout and retest), unchanged, has positive gross and
  net expectancy on XAUUSD after realistic costs on data it was never designed on.
- **Specification and decision rule:** `../strategy-a-forward-test.md` (frozen).
- **Forward data:** signal bars closing from 2026-11-15 23:00 UTC onwards, collected read-only
  by `scripts/forward_observe.py`.
- **Arms:** no cost floor; 0.10R cost floor. Each is evaluated separately at 97.5%.
- **Evaluation:** an arm is evaluated once it has at least 100 events and at least 26 weeks
  of data; it is closed as insufficient data on 2028-11-15. Weekly reports before then are
  descriptive.
- **Outcome language:** supported, negative or inconclusive. "Supported" is evidence, not a
  trading recommendation.
- **Limitations:**
  - entry slippage is assumed (quote observations are not fills);
  - one spread value per bar;
  - the calendar must be kept up to date;
  - a single instrument and strategy, so it is subject to regime changes.
