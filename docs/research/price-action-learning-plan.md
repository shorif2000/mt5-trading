# Price action learning plan for XAUUSD (M15 and H1)

**Purpose:** build an understanding of price action as observable, testable behaviour. This
is a learning plan, not a strategy. Nothing in it changes a rule or justifies a trade. Each
topic pairs a concept with an **objective definition** and a **way to find it in the XAUUSD
history** (the local M15/H1 file, 2022-10 to 2026-10), so that observations can later become
registered hypotheses rather than impressions.

**How to study each topic (about one week each):**
1. Read the foundations. Suggested free sources:
   - BabyPips School of Pipsology (foundations);
   - TradingView education (chart reading and practice);
   - CME Group education (gold futures and market mechanics).
2. Write the concept as a bar rule, as in the table for that topic.
3. Find 20 examples in 2023–2024 history (development data), including ones that *failed*.
4. Record what you saw in a journal: date and time (New York), level, what happened next,
   and whether the rule captured what your eye saw.
5. Don't use 2026 or forward data for discovery. Keep them for testing registered rules.

**Common pitfalls (all topics):**
- Choosing examples that worked (survivorship).
- Defining a pattern only after seeing the outcome (hindsight).
- Using a bar that had not closed at the time (look-ahead).
- Ignoring the spread. On XAUUSD M15, a $3 stop can lose a large share of R to costs alone.

## 1. Market structure

| | |
|---|---|
| Understand | Higher highs and higher lows (uptrend), lower highs and lower lows (downtrend), and structure breaks. |
| Objective definition | **Swing high**: an M15 bar whose high is above the highs of the *k* bars on each side (start with *k* = 3). It is only *confirmed* *k* bars later, and that confirmation lag is the main look-ahead trap. Uptrend: the last two confirmed swing highs and lows are each higher than the one before. |
| In the data | Mark confirmed swings on H1 for one month of 2023. Count how often the structure label changes, and how many bars after the swing the change was known. |
| Exercise | Compare "trend" by swing structure with Version 1.0's EMA50/EMA200 trend on the same days. Where do they disagree? |

## 2. Support and resistance

| | |
|---|---|
| Understand | Levels where price repeatedly reacted, and why some levels matter more (previous day high and low, session extremes, round numbers). |
| Objective definition | A level is any of: `PDH`/`PDL`; the Asian range high and low; a round number (multiples of $10 or $50); a cluster of at least 2 confirmed H1 swing points within 0.25 × `ATRH1`. A **reaction** is price coming within 0.25 × `ATR15` of the level and then moving 1 × `ATR15` away before closing through it. |
| In the data | For each trading day in 2023–2024, record whether price touched `PDH`/`PDL` and whether it reacted or broke. Compare with the same count at random levels, as a baseline. |
| Exercise | Is the reaction rate at real levels different from the random baseline? Without a baseline, any level looks important. |

## 3. Candlestick behaviour

| | |
|---|---|
| Understand | Rejection (long wick), engulfing, inside bars, displacement (a large body), and what each says about who controlled the bar. |
| Objective definitions | **Rejection**: wick ≥ 60% of the bar range on the side away from the close. **Engulfing**: body contains the previous body and has the opposite colour. **Inside bar**: high ≤ previous high and low ≥ previous low. **Displacement**: body ≥ 1.5 × `ATR15`. |
| In the data | Count each pattern by session. Then measure the following 4-bar move in `ATR15` units, *at levels* and *away from levels*. |
| Exercise | Most patterns appear often and mean little on their own. Look for whether location (topic 2) changes what happens next. |

## 4. Breakouts and false breakouts

| | |
|---|---|
| Understand | Continuation versus failure; why a close beyond a level matters more than a wick; retests. |
| Objective definitions | **Breakout**: an M15 close beyond a level by ≥ 0.10 × `ATR15`. **Follow-through**: 1 × `ATR15` further in the breakout direction before a close back inside. **False breakout**: a close back inside within 3 bars. **Retest**: a return to within 0.25 × `ATR15` of the level after the breakout. |
| In the data | For Asian range breakouts in 2023–2024, tabulate follow-through, false breakout and retest frequency by hour. This is the descriptive event study planned before candidate A. |
| Exercise | Read candidates A and C side by side. They are opposite bets on the same event. |

## 5. Liquidity sweeps

| | |
|---|---|
| Understand | Why stops cluster beyond obvious highs and lows, and what a sweep and reclaim looks like. SMC vocabulary is useful only once it is turned into rules. |
| Objective definition | **Sweep**: high ≥ level + 0.10 × `ATR15` and ≤ level + 1.50 × `ATR15`, then a close back below the level within 3 bars. **Market structure shift**: a close below the sweep bar's low (candidate C's confirmation). |
| In the data | List the London-session sweeps of the Asian range high and low in 2023–2024. For each, record how far price travelled back through the range before 16:45. |
| Exercise | Try defining "a sweep that worked" *before* looking at the outcomes, then check it on a later month. |

## 6. Session behaviour

| | |
|---|---|
| Understand | The Asian range, the London open (about 03:00 New York), the New York open (08:00–09:30) and the afternoon; how volatility and spread change across the day. |
| Objective definitions | Sessions as in the approved reports: Asia 19:00–03:00, London 03:00–08:00, New York 08:00–17:00 (New York time). Volatility is mean true range per hour; cost is median bar spread per hour. |
| In the data | Build an hour-of-day table for 2023–2024: average M15 true range, median spread, and the share of daily range made in each hour. |
| Exercise | Find the hours where the typical bar range is small relative to the spread. Those are where costs dominate (the diagnostic's main finding). |

## 7. Risk and trade management

| | |
|---|---|
| Understand | Structural stops, reward to risk and position sizing; why the win rate needed to break even depends on the *realised* (not planned) R. |
| Objective definitions | R = stop distance from the quoted entry. Break-even win rate = 1 / (1 + realised average win in R ÷ average loss in R). Cost in R = (spread + slippage) ÷ stop distance. Position size comes from the existing 2% risk engine, never by eye. |
| In the data | Recompute the break-even win rate for Version 1.0 from the diagnostic tables. Plot cost in R against stop distance. |
| Exercise | Track 1 (break-even exits) shows how trade management redistributes results without creating an edge. Study it when the report is ready. |

## Milestones

1. **Weeks 1–2:** topics 1–2, with a journal of 20 examples each, including failures.
2. **Weeks 3–4:** topics 3–4. Review the A and C event-study tables once they exist.
3. **Weeks 5–6:** topics 5–7. Turn one observation into a draft hypothesis written to the
   registry template, with no tuning.
