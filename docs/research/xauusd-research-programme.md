# XAUUSD research programme (DRAFT for owner approval)

**Status:** draft, 2026-11-10. **Nothing in this document is implemented or run yet.**
Implementation starts only after the owner approves it, track by track.

**Background:** the diagnostic review (`reports/diagnostics/xauusd_v1.0_v1.1_findings.md`)
found no convincing gross edge in Version 1.0 or 1.1. This programme does not repair them. It
does three things:
1. tests one exit question on the existing Version 1.0 entries (Track 1);
2. specifies three alternative strategies, to be tested one at a time (Track 2,
   `xauusd-strategy-candidates.md`);
3. sets out a price action learning plan (Track 3, `price-action-learning-plan.md`).

**Safety:** offline backtesting and read-only MT5 access only. There are no orders, position
or pending-order changes, or execution of any kind. Maximum planned risk stays at 2% of the
balance per trade and is never relaxed to make a result look viable.

## 1. Research integrity rules (all tracks)

1. **Versions frozen.** Version 1.0 and 1.1 code, specifications and reports are never
   changed. New work lives in new modules, specifications and reports.
2. **Register before running.** Every experiment gets a registry entry in
   `docs/research/experiments/` before any result is computed. The entry records the
   hypothesis, data, exact rules, every parameter value, metrics and the decision rule. A
   change after seeing results is a new experiment with a new id; the original stays in the
   record.
3. **No tuning on existing history.** Parameter values are fixed in advance from conventional
   defaults or reasoning recorded in the specification, never chosen by searching 2023–2026.
   Each experiment runs once per registered specification.
4. **How each data period is used:**

   | Period | Status | Use |
   |---|---|---|
   | 2023–2024 | development, viewed | sanity checks and first results |
   | 2025 | validation, viewed for Version 1.0 and 1.1 | one run per registered specification |
   | 2026-01 to 2026-10 | **development evidence** | examined during Version 1.1 design |
   | from 2026-11-01 | **forward hold-out** (not yet viewed) | the only clean test; collected read-only as it accrues |

   A result from 2023–2026 can reject a hypothesis, but on its own cannot establish one. A
   strategy is a candidate only after a registered forward hold-out test with enough events
   (rule 6).
5. **Measured versus assumed.** Each report tables every input as **measured** (spread,
   stop-fill slippage, commission) or **assumed** (entry slippage, market-exit slippage,
   intrabar order). Results are shown under the existing cost scenarios, not just the base.
6. **Events, not candles.** Results are reported per independent setup event (a pullback, a
   breakout, a range touch, a sweep), as well as per trade. One event can produce several
   signal candles, and those must not count as independent evidence. Any period with fewer
   than 100 events is reported as **inconclusive**, whatever its sign.
7. **Two ledgers.**
   - **Fixed risk:** every trade is sized at 2% of a constant £1,000 (a £20 risk limit) and
     results are reported in R. Account-size effects (the 0.01-lot minimum, rounding,
     compounding) then don't change which trades are taken.
   - **Compounding:** 2% of the running balance, as in Version 1.0.

   Both are reported, and conclusions are drawn from the fixed-risk ledger.
8. **Realistic costs.**
   - Spread is the historical bar spread.
   - Stop exits use the measured stop-slippage percentiles (base p90 = 40 points).
   - Entry and market-exit slippage use the labelled scenarios (0, 7 and 40 points).
   - Commission is £0 (measured).
   - Swap is 0 only while no position is held overnight.
9. **Multiple comparisons.** Each report states how many experiments and buckets have been
   examined so far. Sub-group results (sessions, regimes) are hypotheses for forward testing,
   never conclusions.
10. **Data limitations stated.** Every report lists the intrabar and data limitations in
    section 2.

## 2. Data inventory and limitations

| Data | Available | Limitation |
|---|---|---|
| XAUUSD M15 and H1 bid OHLC with bar spread | 2022-10-30 to 2026-10-30 (local file) | one spread value per bar; order of high and low within a bar unknown; no tick volume stored |
| GBPUSD M15 | same range | used for GBP conversion |
| XAUUSD M1 | **unconfirmed; likely only from about 2026-07-31** (one read-only probe, 2026-11-10) | probe incomplete because the MT5 bridge stopped responding; must be re-checked |
| XAUUSD ticks | **unknown** (the probe timed out) | must be re-checked |
| Stop and take-profit fill slippage | measured from the account's own deals | applied as fixed percentiles, not conditioned on time or volatility |
| Entry slippage | **not measurable** (MT5 records no requested price for market orders) | scenarios only |
| Economic calendar | **none** | news restrictions can't be applied; stated as a limitation |
| Tick volume (for a VWAP proxy) | in MT5 `get_rates`, **not in the local history file** | needs a read-only re-collection if VWAP is used |

**Action before Track 1:** restart the MT5 bridge, then establish (read-only) the earliest
XAUUSD M1 bar and the earliest tick, and record them in the Track 1 registry entry. The
bridge reported "port in use" on restart; that needs fixing on the bridge host.

## 3. Track 1: break-even exit research (experiment EXP-001)

### 3.1 Can the engine model the stop move without look-ahead?

**On M15 bars alone, not exactly.** The engine knows each bar's open, high, low and close, but
not the order in which the high and low occurred. Two kinds of event are ambiguous:

- **In the trigger bar:** a bar reaches +0.5R and also returns to the entry price. Did the
  break-even stop exist before the return? M15 data cannot tell.
- **In the stop-and-trigger bar:** a bar touches both the original stop and the trigger level.
  The engine already assumes the stop came first, which is conservative.

**The resolution is to specify a stop-management rule that M15 data models exactly, rather
than approximating an intrabar rule:**

- **Primary (exact on M15): bar-close management.** After an M15 bar *closes*, if the
  favourable excursion so far has reached the trigger, the stop moves to break-even from the
  *next bar's open*. Within the trigger bar, the original stop and target still apply,
  checked as the engine does now. An automated system could implement this exactly (it acts
  on each new bar), so the backtest models a real, implementable rule with no look-ahead.
- **Secondary (intrabar, limited data): tick or M1 management.** The stop moves the moment
  the trigger is touched. This needs M1 bars at minimum (M1 still has the same problem at
  one-minute scale) or ticks. It can only be run where that data exists (probably
  2026-07-31 onwards, about 3 months, too few events to conclude anything). It is reported as
  a cross-check of the primary rule only, with a count of the bars where it remained
  ambiguous.

**Bounds:** for the primary rule, the report also counts trigger bars that touched the
break-even level in the same bar. Those trades are recomputed under both orderings, as a
best-case and a worst-case bound.

### 3.2 Specification

- **Entries:** the Version 1.0 base-scenario trade list, all three periods: 823 + 498 + 378
  trades. Each trade keeps its entry time, fill, initial stop, target, quoted entry and
  volume.
- **Fixed entries:** an earlier break-even exit does **not** allow a new entry that Version
  1.0 skipped while the position was open, so the comparison isolates the exit rule. This is
  stated as a limitation: a live system might have taken those extra trades.
- **R distance:** |quoted entry − initial stop|, the basis for the Version 1.0 target.
- **Favourable excursion:**
  - longs: bid high minus entry fill;
  - shorts: entry fill minus (low + bar spread), so measured on the ask.

| Variant | Trigger (favourable excursion) | New stop |
|---|---|---|
| BE-0 (control) | none | unchanged (reproduces Version 1.0 exactly; must reconcile) |
| BE-0.5 | 0.5R | entry fill |
| BE-0.75 | 0.75R | entry fill |
| BE-1.0 | 1.0R | entry fill |
| BE-1.0+C | 1.0R | entry fill plus estimated round-trip cost (entry-bar spread + 7 points + 40 points) in the trade's favour, rounded away from the entry to the tick |

- **Rules unchanged from Version 1.0:** target, forced close at 16:45 New York and H1 trend
  exit.
- **Break-even stop fills:** a break-even exit is a stop exit, so it takes the same stop
  slippage as any stop (p90 = 40 points in the base; all percentiles in the grid). Shorts pay
  the exit-bar spread. A gap through the break-even stop fills at the bar open.
- **Cost scenarios:** the full existing grid. Base: 7-point entry slippage, p90 stop
  slippage.

### 3.3 Measures (per variant, per period, both ledgers)

- Net and gross expectancy per trade and per event (R and GBP).
- Profit factor, win rate, average win, average loss.
- Maximum drawdown (R on the fixed-risk ledger; GBP and % on the compounding ledger).
- Exit mix: target, original stop, break-even stop, forced close, trend exit.
- **Break-even stops that later reached the original target:** after a break-even exit, the
  original stop and target are replayed on the following bars until the 16:45 forced close.
  The count of trades that would have reached the target first is reported. Same-bar
  ambiguity is resolved stop-first.
- **Additional costs:** extra stop slippage and spread from break-even exits, in GBP and R,
  compared with the control.
- Ambiguous trigger bars (count), with best-case and worst-case bounds.

### 3.4 Decision rule (pre-registered)

**No variant is selected from 2023–2026.** The report is descriptive. A variant can only be
carried forward if all three of the following hold:
1. its fixed-risk **gross** expectancy is above the control's in all three periods;
2. it does not rely on the zero-entry-slippage scenario;
3. its result is then confirmed on the forward hold-out.

Even then, it would only apply to a strategy that shows a gross edge in its own right. A
break-even rule cannot create an edge where none exists. It only changes how results are
distributed.

## 4. Track 2: alternative strategies

Specifications are in `xauusd-strategy-candidates.md`:

| Candidate | Status |
|---|---|
| A. Session breakout and retest | specified |
| B. Range mean reversion | specified |
| C. Liquidity sweep and failed breakout | specified |
| D. Volatility (Donchian) breakout | parked; outline only |

**Proposed order:** one strategy at a time, starting with **A**, then **C**, then **B**.
- A and C use the same reference levels (Asian range, previous day high and low), so they
  share a read-only event study.
- B needs a range-detection component and possibly tick volume.

**Before each strategy runs:**
1. A registered event study of its setup *events* (descriptive only: frequency, follow-through,
   cost relative to stop distance) on 2023–2024.
2. A registered backtest across all periods with the fixed parameters in its specification.
3. Forward hold-out collection.

## 5. Track 3: price action learning

See `price-action-learning-plan.md`. It is a reading and observation plan. Each concept is
paired with an objective definition and a way to locate it in the XAUUSD history. Nothing in
it changes a strategy.

## 6. Decisions requested from the owner

1. Approve the integrity rules (section 1), including treating data from 2026-11-01 as the
   forward hold-out.
2. Approve EXP-001 (section 3), with bar-close management as the primary rule.
3. Approve the candidate specifications, and confirm the order A → C → B with D parked.
4. Allow a read-only re-check of M1 and tick history depth once the MT5 bridge is restarted.
5. Choose whether to source a static economic calendar from official schedules (FOMC, BLS
   CPI and payrolls release dates), so that news restrictions can be applied.
