# XAUUSD alternative strategy candidates (DRAFT for owner approval)

**Status:** draft, 2026-11-10. **Specifications only. None of these is implemented or tested,
and none is claimed to be profitable.** Each is a hypothesis, to be tested one at a time under
the rules of `xauusd-research-programme.md`.

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
