# XAUUSD alternative strategy candidates (DRAFT for owner approval)

**Status:** approved by the owner on 2026-11-10 with the recommended defaults (the cost
floor, the fixed values and the order A, C, B, with D parked). Amendment 1 (2026-11-11, at the
end) records clarifications made before any result was computed. No numeric parameter
changed. **None of these is claimed to be profitable.**

The parameter values below are fixed in advance. They are conventional or reasoned choices
recorded here, not values found by searching 2023–2026 data. Changing any of them after
results are seen creates a new registered experiment.

The illustrative charts supplied with the request (a breakout and retest on gold H4, a forex
range, a schematic liquidity sweep, a Donchian indicator on gold M5) explain the concepts.
They are not rules, and they were not used to choose any value.

## 0. Common definitions (all candidates)

| Item | Definition |
|---|---|
| Time | America/New_York. Gold trading day *d* runs 18:00 on *d−1* to 17:00 on *d*. |
| Bars | Completed XAUUSD M15 and H1 bid bars from the existing history. Ask = bid + bar spread. |
| `ATR15` | ATR(14) of completed M15 bars at the signal bar (existing `atr_series`, MT5 method). |
| `ATRH1` | ATR(14) of completed H1 bars at the last completed H1 bar. |
| `ADR` | ATR(14) of daily bars built from M15 over completed gold trading days only. |
| Asian range | `AR_H` and `AR_L` = highest high and lowest low of the M15 bars opening 19:00–01:45 of day *d*. Valid only if every bar in that window exists. Usable from 02:00. |
| Previous day | `PDH` and `PDL` = high and low of trading day *d−1*. Usable from 18:00 on *d−1*. |
| Entry | Market order at the open of the bar after the signal bar: buy at ask, sell at bid. |
| Entry-time rules | Unchanged from Version 1.0: no entries 16:00–19:00; forced close 16:45; no overnight positions; no entries on dates with an unconfirmed holiday schedule; no entries with missing candles in the decision window. |
| Spread | Signal and entry bar spreads ≤ 35 points (the Version 1.0 value, reused unchanged). |
| Cost floor | Estimated cost `C` = entry-bar spread + 7 + 40 points. Skip if `C` > 0.10 × stop distance, i.e. the stop must be at least 10 × `C` (about $6.90 at today's spread). See open point 1. |
| Risk | 2% maximum through the existing risk engine. Reject when the 0.01-lot minimum exceeds 2%. Fixed-risk and compounding ledgers both reported. |
| Positions | One open position per strategy. One trade per setup event. |
| News | When a reliable calendar exists: no entries from 30 minutes before to 15 minutes after a high-impact USD release. Until then, every report is labelled "not news-filtered". |
| Rounding | Stops are rounded to the tick away from the entry; targets towards it (Version 1.0 convention). |

## A. Session breakout and retest

**Hypothesis:** when London or New York trading breaks the Asian range, the broken boundary
holds on a retest and price continues in the breakout direction.

| Element | Long (short is the mirror image) |
|---|---|
| Market condition | Asian range valid, with 0.15 × `ADR` ≤ `AR_H` − `AR_L` ≤ 0.60 × `ADR` (a compressed range, but not a trivial one). No trend filter, so A is independent of Version 1.0. |
| Breakout | The first M15 bar opening 02:00–10:45 whose **close** > `AR_H` + 0.10 × `ATR15`. Only the first breakout of each side each day counts. |
| Retest | Within the next 12 M15 bars: a bar with low ≤ `AR_H` + 0.25 × `ATR15` **and** low ≥ `AR_H` − 0.50 × `ATR15`. |
| Confirmation (signal bar) | The retest bar or a later bar in the window with close > `AR_H`, close > open, and close in the upper half of its range. |
| Entry | Next bar open, no later than 11:00. |
| Stop | Lowest low from the breakout bar to the signal bar, minus 0.20 × `ATR15`. |
| Target and R:R | Quoted entry + 2.0 × stop distance (planned 2R). Forced close at 16:45. |
| Stop limits | Stop distance ≤ 3.0 × `ATR15`, and the cost floor applies. |
| Sessions | Breakouts 02:00–10:45 (London and early New York); entries until 11:00. |
| Invalidation before entry | Any M15 close < `AR_H` − 0.10 × `ATR15` (a failed breakout); the 12-bar window ends; it is 11:00; a spread limit is exceeded. |
| Event | One per (trading day, side). At most one trade per day for A. |
| Data | M15 only (existing file). `ADR` derived from M15. |

## B. Range mean reversion

**Hypothesis:** when gold is range-bound on H1, rejections at a range boundary on M15 revert
towards the middle of the range. (The diagnostic found the trend strategy losing in
range-bound H1 conditions. That motivates the question, but does not support this
hypothesis.)

| Element | Long at the range low (short at the range high is the mirror image) |
|---|---|
| Range | At the last completed H1 bar: `R_H` and `R_L` = highest high and lowest low of the last 48 completed H1 bars; `W` = `R_H` − `R_L`. |
| Market condition | 4 × `ATRH1` ≤ `W` ≤ 10 × `ATRH1`; H1 ADX(14) (Wilder) < 20; at least 2 boundary tests at each side; last H1 close inside [`R_L`, `R_H`]. |
| Boundary test | An H1 bar with low ≤ `R_L` + 0.25 × `ATRH1`. Tests closer than 6 H1 bars to each other count once. |
| Signal bar (M15) | Low ≤ `R_L` + 0.25 × `ATRH1`; low ≥ `R_L` − 0.50 × `ATR15` (limited penetration); close ≥ `R_L`; close > open; (close − low) ≥ 0.60 × (high − low), i.e. a rejection wick. |
| Entry | Next bar open. |
| Stop | min(signal low, `R_L`) − 0.30 × `ATR15`. |
| Target and R:R | Range midpoint (`R_H` + `R_L`) / 2. Skip if the planned reward:risk from the quoted entry is < 1.2. Forced close at 16:45. |
| Stop limits | Stop distance ≤ 3.0 × `ATR15`, and the cost floor applies. |
| Sessions | All permitted hours: entries 19:00–16:00. |
| Invalidation | Range conditions fail at the latest completed H1 bar; an H1 close outside the range by more than 0.25 × `ATRH1` ends that range. After a stop-out at a boundary, no new entry at that boundary until the 48-bar range changes. |
| Event | One per (range, boundary test cluster). |
| VWAP | **Not used in this specification.** A session VWAP with tick volume as the weight (a proxy; spot gold has no real volume) may be recorded as a descriptive covariate. That needs a read-only re-collection of history with tick volume. |
| Data | M15 and H1 (existing). ADX(14) is a new indicator, needing unit tests. |

## C. Liquidity sweep and failed breakout

**Hypothesis:** brief moves beyond obvious reference levels that fail to hold reverse back
through the level. Smart-money-concepts (SMC) terms are replaced by bar rules; for example,
"stop hunt" becomes a breach of 0.10–1.50 `ATR15` followed by a close back inside.

| Element | Short after a sweep of a high level `L` (a long after sweeping a low level is the mirror image) |
|---|---|
| Levels | `AR_H` (valid 02:00–11:00) and `PDH` (valid 19:00–14:00). |
| Sweep | An M15 bar with high ≥ `L` + 0.10 × `ATR15` and high ≤ `L` + 1.50 × `ATR15`. Only the first sweep of each level each day counts. |
| Reclaim | The sweep bar or one of the next 2 bars closes < `L`. |
| Confirmation (signal bar) | Within 4 bars after the reclaim, a bar closes below the sweep bar's low, while still below `L`. |
| Entry | Next bar open. |
| Stop | Highest high from the sweep bar to the signal bar, plus 0.20 × `ATR15`. |
| Target and R:R | Quoted entry − 2.0 × stop distance (planned 2R). Forced close at 16:45. |
| Stop limits | Stop distance ≤ 3.0 × `ATR15`, and the cost floor applies. |
| Sessions | Entries 02:00–14:00. |
| Invalidation before entry | A close above the sweep high; the reclaim or confirmation window ends; the level was already swept earlier that day. |
| Event | One per (trading day, level, side). |
| Relation to A | A's "failed breakout" invalidation at `AR_H` can be a C event at the same level. A and C are opposing hypotheses about the same events. They are tested separately, and the overlap is reported. |
| Data | M15 only (existing file). |

## D. Volatility (Donchian) breakout: parked

The owner's notes also suggest a Donchian-channel breakout with ATR expansion and a trailing
stop. **It is not specified here**, because the task limits this round to three strategies.
If chosen later, it needs the same treatment:
- fixed channel lengths;
- an objective volatility-expansion rule;
- a trailing stop modelled on bar closes (intrabar trailing has the same data problem as
  Track 1);
- a cost floor.

## Open points for the owner

1. **Cost floor.** Skip trades whose estimated cost exceeds 0.10R. This is a cost-realism
   constraint, set before any of these strategies is tested. The diagnostic showed that tight
   stops are dominated by costs, so the floor is informed by viewed data. Approve it, or test
   without it.
2. **Fixed values.** Approve the values above as fixed, including the A width band
   (0.15–0.60 × `ADR`), the B range test (48 H1 bars, ADX < 20) and the C sweep band
   (0.10–1.50 × `ATR15`).
3. **Order.** Implement A first, then C (which reuses A's levels), then B.
4. **Variants.** A previous-day-high-and-low version of A, and an Asian-range-only version of
   C, are possible later experiments. They are *not* part of this round.

## Amendment 1 (2026-11-11): clarifications before any result

Made before any EXP-002 to EXP-007 result was computed. Each item makes an existing rule
deterministic; none changes a numeric parameter.

### Common

1. **Trading day:** the trading day of a moment *t* is the New York date of *t* + 6 hours
   (18:00 opens the next day).
2. **`ADR`** on day *d* is ATR(14) of the daily bars of completed trading days up to *d* − 1.
   Daily bars are aggregated from the M15 bars of each trading day.
3. **One trade per event:** each strategy emits only the **first** qualifying signal of an
   event. Later candles of the same event are not signals, so trades and events are counted
   one-to-one.
4. **Signals while a position is open** are recorded as skipped ("position already open"),
   not silently dropped.
5. **Missing data:** every bar used in a decision (the Asian window, the bars from breakout or
   sweep to signal, the 48 H1 bars of a range) must be present and consecutive. Otherwise the
   event is recorded as "data incomplete".
6. **Timing:** a signal bar must open no later than 15 minutes before the last allowed entry
   time, so the entry (next bar open) is inside the window.
7. **Cost floor and news:** see programme Amendment 1 (A1.3, A1.4).

### A. Session breakout and retest

- **Breakout test order:** bars are scanned in time order from 02:00. The first bar meeting
  the breakout rule for a side is that side's breakout; a later breakout on the same side is
  ignored.
- **Window:** retest, confirmation and invalidation are checked bar by bar over the 12 bars
  after the breakout bar. In each bar, invalidation (close < `AR_H` − 0.10 × `ATR15`) is
  checked first. A confirmation needs a retest at that bar or earlier.
- **Priority when both sides qualify on one day:** the day's single A trade opportunity is
  the confirmed signal with the **earlier signal bar**. The other side is recorded as
  "superseded" and is not traded, even if the first is later filtered or rejected. Both sides
  confirming on the same bar is impossible (a close above `AR_H` and below `AR_L`). If it
  ever occurred, both are recorded as "conflict" and neither is traded.
  - *Rationale:* chronological priority is what a live system would do. It doesn't depend on
    code execution order or on the outcome.

### C. Liquidity sweep and failed breakout

- **Approach from inside:** the sweep bar must **open below** `L` (above it for a low level).
  "Moves beyond a previous high" presumes price was below it. A bar opening beyond the level
  is a gap, recorded as "opened beyond level", and ends the level for the day.
- **First breach only:** the first bar of the day with high ≥ `L` + 0.10 × `ATR15` is the
  level's only candidate. If its high exceeds `L` + 1.50 × `ATR15`, the event is recorded as
  "displacement, not a sweep" and the level is finished for the day.
- **Windows:** reclaim = a close < `L` on the sweep bar or one of the next 2 bars.
  Confirmation = the first of the 4 bars *after* the reclaim bar with close < the sweep bar's
  low (and < `L`). Invalidation (close > the sweep bar's high) is checked first in each bar.
- **Level windows:** `AR_H`/`AR_L` sweep bars open 02:00–10:45; `PDH`/`PDL` sweep bars open
  19:00 (previous calendar day) to 13:45. Signal bars open 01:45–13:45 (entries 02:00–14:00).
- **Ties:** two events signalling on the same bar in the same direction produce one trade,
  attributed to the previous-day level, which takes priority over the Asian level (the longer
  reference). Opposite directions on the same bar are recorded as "conflict" and neither is
  traded.

### B. Range mean reversion

- **Range at time *t*:** computed from the 48 completed H1 bars ending with the last completed
  H1 bar before *t*. "Last H1 close inside [`R_L`, `R_H`]" is always true by construction,
  because that bar is in the window. It is kept, but has no effect.
- **Range break:** an H1 close below `R_L` − 0.25 × `ATRH1`, or above `R_H` + 0.25 × `ATRH1`,
  of the range as it stood at the previous H1 bar ends that range. No B entries are allowed
  while the breaking bar is inside the 48-bar window, i.e. until the range has been rebuilt
  without it.
- **Boundary test clusters:** test bars at a boundary that are less than 6 H1 bars apart
  belong to one cluster.
- **Event:** a visit to a boundary. M15 bars in the boundary zone (low ≤ `R_L` + 0.25 ×
  `ATRH1`) belong to the same visit unless 6 H1 bars (24 M15 bars) pass without one. One
  trade per visit.
- **Stop-out block:** after a stop-out at a boundary, that boundary (its exact `R_L` or `R_H`
  value) is blocked until the 48-bar range has a different value for it.
- **Target:** the midpoint, rounded to the tick towards the entry. The 1.2 reward:risk check
  uses the quoted entry at the fill, as the Version 1.0 target does.
- **Range-break exit:** none while a trade is open. The stop and the forced close manage it.
  The spec defines no other exit.
- **ADX(14):** Wilder's method, on completed H1 bars.
