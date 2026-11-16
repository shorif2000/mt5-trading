# Strategy A, FX pool: frozen specification (EXP-013 historical, EXP-014 forward)

**Status:** frozen 2026-11-16, before any backtest or forward result exists. Checksums in
`strategy-a-fx-pool-freeze.json`. A changed rule after this point is a new experiment with a
new id; this one is never edited. Research only. **No orders are placed.**

## 0. Why this exists

EXP-011 (XAUUSD) needs about 10–11 months to accumulate 100 forward events at the 2023–24
rate. Owner decision 2026-11-16: pool Strategy A, unchanged, across EURUSD, GBPUSD and USDJPY
too, so the combined event count reaches the same threshold faster. This changes what a
positive result would mean — from "works on XAUUSD" to "works across these four
instruments" — and that broader claim needs its own robustness check (section 4). EXP-011
itself is untouched: its own forward stream, freeze and reports continue exactly as
registered.

## 1. Instruments and conversion (verified read-only, 2026-11-16)

| Symbol | Verified against | Base / quote | Contract | Tick size | Digits | Commission |
|---|---|---|---|---|---|---|
| EURUSD | `list_symbols`, `get_symbol_info` | EUR / USD | 100,000 | 0.00001 | 5 | £0 (43 deals, all 0) |
| GBPUSD | `list_symbols`, `get_symbol_info` | GBP / USD | 100,000 | 0.00001 | 5 | £0 (42 deals, all 0) |
| USDJPY | `list_symbols`, `get_symbol_info` | USD / JPY | 100,000 | 0.001 | 3 | £0 (10 deals, all 0) |

Commission evidence is from every real deal in this account's history for each symbol
(`get_history_deals`), the same method used for XAUUSD, though with far fewer deals (10–43
against gold's 18,466): treated as sufficient to confirm £0 (a consistent spread-based-pricing
account, not commission-based), not as a statistically powerful estimate.

**Conversion to GBP** (`src/trading/research/multi_market.py`, `GenericCandidateBacktest`):

| Traded | Conversion pair | Why |
|---|---|---|
| EURUSD | GBPUSD | both USD-quoted; GBP per USD from the GBPUSD bar, as for XAUUSD |
| GBPUSD | GBPUSD (itself) | USD-quoted P&L on a GBP-base pair; same single-leg formula |
| USDJPY | GBPJPY | JPY-quoted; GBP per JPY from the GBPJPY bar directly, verified to exist on this broker, so no composed GBPUSD x USDJPY cross is needed |

GBPJPY is a conversion rate only; it is never traded by this specification.

## 2. What is reused from Strategy A unchanged

Everything in `docs/research/xauusd-strategy-candidates.md` section A and its Amendment 1
(the Asian-range breakout and retest rule itself, chronological day priority, ATR-based stop,
2R target), the 0.10R cost floor definition (programme A1.3), and the FOMC/CPI/Employment
Situation news filter (all three instruments carry USD on one leg, so the same calendar
applies). None of this is changed for the FX pool.

## 3. What is different for EURUSD/GBPUSD/USDJPY, and why

- **No forced close, no no-entry window** (owner decision 2026-11-16). Gold's 16:45 New York
  forced close and 16:00–19:00 no-entry window (Version 1.0 Amendment 1) exist because gold
  has an actual daily break at 17:00–18:00 New York. `config/market_sessions.yaml`'s "forex"
  profile confirms EURUSD/GBPUSD/USDJPY trade continuously (Sunday 17:00 to Friday 17:00 New
  York) with no such break, so there is no equivalent time to anchor a forced-close rule to.
  A position runs until its stop or the 2R target only.
- **Stop and entry slippage are carried-over assumptions, not measured for these instruments.**
  The existing cost grid (`config/backtest.yaml`: entry 0/7/40 points; stop-exit percentiles
  p50/p90/p95/p99 = 7/40/60/140 points) was derived from **gold's own** 6,583 measured stop
  exits. EURUSD/GBPUSD/USDJPY have only 10–43 deals each in this account — far too few to
  derive a comparable percentile. The same point-count grid is applied to them for
  methodological consistency with EXP-003/005/007-010, but every report states plainly that,
  for the FX instruments, only **spread** is measured; entry and stop-exit slippage are
  assumed, carried over from gold's evidence, not this instrument's own.
- **Commission** is measured for each instrument (above), not carried over.

## 4. Decision rule for the pooled forward test (EXP-014)

Extends EXP-011's rule (`strategy-a-forward-test.md` section 3) rather than replacing it.
Each arm (no floor; 0.10R floor) is still evaluated separately, at the same 97.5% level.

- **Pooled event count:** the sum of events across all four instruments (XAUUSD from EXP-011
  + EURUSD + GBPUSD + USDJPY), still against the same thresholds: **100 events and 26 weeks**
  since the shared forward start. 2026-11-15 23:00 UTC is this pool's forward start too, the
  same moment as EXP-011's, so all four streams accrue on one clock.
- **Closing date:** 2028-11-15, same as EXP-011.
- **All six of EXP-011's criteria**, computed on the pooled sample (gross positive, net
  positive, 97.5% CI lower bound above 0, sum of R without the best 10 trades positive, net
  positive in the 40-point entry stress scenario, net positive in at least two of three
  volatility terciles — cut-offs computed **per instrument** from that instrument's own
  2023–2024 ADR ratio, since absolute ADR scales are not comparable across gold and FX, before
  pooling the bucketed trades).
- **Plus one more, specific to pooling:** net R positive in **at least three of the four
  instruments individually**. This is the direct check against the broader claim: a pooled
  result driven by one instrument alone is not "works across majors."
- **Per-instrument results are always reported alongside the pooled figure**, never only the
  pooled number.
- **Outcome language is unchanged:** supported / negative / inconclusive, and "supported" is
  evidence, not a recommendation to trade (the same caveat as EXP-011).

## 5. Historical event study and backtest (EXP-013)

Descriptive, on 2023–2026 data (development evidence, viewed, exactly as for XAUUSD):
per-instrument event study and backtest, same periods (Training 2023–24, Validation 2025,
2026 development), same two arms, same cost grid, same fixed-risk and compounding ledgers, same
news filter. Reported per instrument; no pooled historical claim, since pooling only applies to
the forward decision rule above.

## 6. Observation procedure

Mirrors `strategy-a-forward-test.md` section 4, generalised to four instruments:
`scripts/forward_observe.py` (EXP-011, XAUUSD, untouched) and a parallel, separate observer
for this pool (`scripts/fx_pool_observe.py`) write to `data/forward/fx_pool_*`, never to
EXP-011's files. The weekly monitor reports each instrument and the pooled figure together.

## 7. Not allowed

Same as `strategy-a-forward-test.md` section 5: no rule changes after this freeze, no
selective reporting, no using 2026-11-01 to 2026-11-16 FX data as forward evidence (collected
and analysed read-only this session, so not blind either), no execution of any kind.
