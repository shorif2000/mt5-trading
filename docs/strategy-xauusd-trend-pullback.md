# XAUUSD M15 Intraday Trend Pullback Strategy

**Status:** Version 1.0, approved by the account owner on 2026-11-10, with amendment 1 below.

**Amendment 1 (owner decision, 2026-11-10):** strategy positions are force-closed at
**16:45 America/New_York**, 15 minutes before gold's 17:00 daily break. This replaces "at least
30 minutes before the scheduled daily break" in section 6 and the 16:30 time in Appendix A
point I. No new entries within 60 minutes either side of the break (16:00 to 19:00 New York) is
unchanged. No overnight or weekend positions. US daylight saving is handled by working in New
York time.

**Commission:** the owner reports a Vantage **Standard swap-free** account. Commission is
verified against the account's own deal history before it is recorded as 0.
**Instrument:** XAUUSD
**Entry timeframe:** M15
**Trend timeframe:** H1
**Trading style:** Intraday trend following
**Holding period:** Intraday only
**Maximum risk:** 2% of the account balance per trade (see open point A)
**Execution:** Research and backtesting only. No live order execution.

Sections 1 to 11 are the specification as provided by the account owner. Appendix A lists the
points that must be decided before implementation, each with a proposed interpretation.
Appendix B gives what the current broker specification implies for a GBP 100 account.

## 1. Strategy objective

Identify established short-term trends in gold, wait for a temporary pullback, and enter when
price resumes in the direction of the prevailing trend.

The strategy should favour selective, higher-quality setups rather than generating a large
number of trades.

Both long and short positions are permitted.

## 2. Market trend identification (H1)

Use the following indicators on completed H1 candles:

- EMA 50: intermediate trend.
- EMA 200: longer-term trend.

**Bullish trend:**
- EMA 50 is above EMA 200.
- EMA 50 is higher than its value five completed H1 candles earlier.
- H1 candle closes above EMA 50.

**Bearish trend:**
- EMA 50 is below EMA 200.
- EMA 50 is lower than its value five completed H1 candles earlier.
- H1 candle closes below EMA 50.

If these conditions are not satisfied, there is no trade.

The strategy must not anticipate an H1 candle closing. Only completed candles can establish
the trend.

## 3. Entry conditions (M15)

Use the following indicators on completed M15 candles:

- EMA 20: short-term pullback reference.
- ATR 14: volatility measurement.
- Recent candle highs and lows: pullback structure.

### Long entry

All conditions must be satisfied:

1. H1 trend is bullish.
2. M15 price pulls back towards or below EMA 20.
3. The pullback does not invalidate the broader H1 bullish trend.
4. A completed M15 candle closes back above EMA 20.
5. That candle closes above the previous M15 candle's high.
6. The signal candle is bullish.
7. No other strategy position is currently open.

Enter at the next available executable ask price after the signal candle closes.

### Short entry

Apply the inverse conditions:

1. H1 trend is bearish.
2. M15 price pulls back towards or above EMA 20.
3. The pullback does not invalidate the broader H1 bearish trend.
4. A completed M15 candle closes back below EMA 20.
5. That candle closes below the previous M15 candle's low.
6. The signal candle is bearish.
7. No other strategy position is currently open.

Enter at the next available executable bid price after the signal candle closes.

No entry is permitted using information from an unfinished candle.

## 4. Stop loss

Use recent price structure to determine the stop.

**Long:**
- Identify the lowest low of the pullback, including the signal candle.
- Place the stop below that low by a buffer of 0.2 × M15 ATR(14).

**Short:**
- Identify the highest high of the pullback, including the signal candle.
- Place the stop above that high by a buffer of 0.2 × M15 ATR(14).

Round the stop to the permitted broker price increment.

The stop must also comply with the broker's minimum stop distance and freeze restrictions.

Reject the setup if the stop is invalid, excessively wide or cannot be supported by the
permitted position size.

## 5. Take profit and trade management

Initial target: 2 times the initial monetary risk (2R).

For example, if the estimated risk is £1, the initial target is £2 before any additional costs.

Initial research rules:

- No partial profit taking.
- No averaging down.
- No adding to losing positions.
- No martingale.
- No automatic increase in position size after a profitable trade.
- No discretionary stop adjustment.
- No trailing stop in the initial strategy version.

Close the position if the stop or target is reached.

Also close if the H1 trend becomes invalid, using completed H1 candles only.

A position must never remain open through the broker's daily rollover.

## 6. Trading hours and rollover

Use broker server time and verified XAUUSD trading sessions.

- Do not open positions close to the daily market break.
- Close all strategy positions at least 30 minutes before the scheduled daily break.
  *(Amended: 16:45 New York, see amendment 1.)*
- Do not open new positions within 60 minutes of the scheduled daily break.
- Do not hold positions over weekends.
- Reject trades if the broker's session schedule or server time cannot be established
  reliably.

The rollover cutoff must be configurable rather than hardcoded to a fixed UTC time.

## 7. Risk management

The maximum permitted risk is 2% of the current account balance.

Maximum risk = Current account balance × 0.02

For a £100 account, the maximum permitted risk is £2.

Position sizing must:

- Use MT5's loss tick value.
- Account for the stop distance, spread, commission and configured slippage.
- Use the account currency (GBP) correctly.
- Round volume down to the broker's permitted volume step.
- Reject the trade if minimum permitted volume exceeds the 2% limit.
- Recalculate the estimated loss using the final volume.
- Reject missing, stale or inconsistent account and instrument data.

The 2% limit must never be relaxed to accommodate a strategy signal.

Only one position may be open under this strategy at a time. Existing positions and pending
orders must be reported separately. They must not be silently netted against this strategy's
risk calculation.

## 8. Trade avoidance conditions

Do not open a trade when:

- H1 trend conditions are not met.
- The pullback or entry conditions are incomplete.
- The stop distance is too large for the 2% risk limit.
- Minimum volume exceeds the risk limit.
- Spread exceeds a configurable maximum.
- Market data is stale or incomplete.
- The instrument is outside its verified trading session.
- There is insufficient historical data to calculate the indicators.
- A high-impact USD economic announcement is within the configured blackout period, provided
  a reliable economic calendar is available.

Initial news filter proposal: no new entries 30 minutes before and 15 minutes after
high-impact USD announcements. This needs a reliable event source and must be tested
separately.

## 9. Backtesting requirements

The backtest must use historical bid and ask prices where available.

It must account for:

- Spread.
- Commission.
- Slippage.
- Broker minimum volume and volume increments.
- Tick size and loss tick value.
- Price precision.
- Trading sessions and daily breaks.
- Stop loss and take profit execution assumptions.
- Intraday forced closure.
- Missing candles and invalid historical data.

Avoid look-ahead bias and repainting. Indicators and signals must use only information
available at the time of the simulated decision.

Where historical tick data is unavailable, document the limitations of candle-based stop and
target simulation. If both stop and target are touched within one candle and their order
cannot be established, use a conservative assumption.

## 10. Performance evaluation

Report at least:

- Total signals generated.
- Trades accepted and rejected by risk management.
- Trades rejected because of minimum volume.
- Trades rejected by margin requirements.
- Win rate.
- Gross and net profit.
- Profit factor.
- Average win and average loss.
- Maximum drawdown.
- Expected value per trade.
- Maximum consecutive losses.
- Average holding duration.
- Spread, commission and slippage costs.
- Performance by trading session.
- Performance by month.
- Number of trades that were executable at the account's minimum volume.

Use chronological training, validation and out-of-sample test periods. Do not optimise
parameters against the entire dataset.

A strategy with too few trades or insufficient out-of-sample evidence must be reported as
inconclusive, not profitable.

## 11. Implementation restrictions

This document defines the proposed strategy only.

Do not implement the strategy until the user explicitly approves the specification.

Do not connect to the live account for testing, enable Algo Trading, submit orders, modify
existing positions or pending orders, or introduce execution functionality.

---

## Appendix A: open points to decide before implementation

Each point has a **proposed interpretation**. Approving the specification without changes
approves these interpretations.

**A. Which balance sets the 2% limit.** Section 7 says the current MT5 account balance. The
earlier decision was a **virtual GBP 100 paper ledger**, with MT5 used only for data. The
current real account balance (excluding credit) is well below GBP 100, which would give a
limit of a few tenths of a pound and leave almost no executable trades.
*Proposed:* the backtest uses the paper ledger, starting at GBP 100 and updated by each
simulated trade's net result. The sizing code's live-balance path is unchanged for future use.

**B. "Pulls back towards EMA 20" (3.2).** "Towards" needs a threshold.
*Proposed:* a completed M15 candle's low is at most 0.25 × ATR(14) above EMA 20, or below it
(mirrored for shorts). This must happen within the last 8 completed M15 candles before the
signal.

**C. "Does not invalidate the H1 trend" (3.3).** *Proposed:* all three H1 trend conditions
still hold at the most recently completed H1 candle when the signal candle closes.

**D. Extent of the pullback for the stop (4).** *Proposed:* the pullback runs from the first M15
candle that met point B up to and including the signal candle, capped at 8 candles.

**E. "Excessively wide" stop (4).** *Proposed:* the stop is rejected if its distance from the
entry exceeds 3 × M15 ATR(14), regardless of the risk check.

**F. 2R target (5).** "2 times the initial monetary risk" depends on costs.
*Proposed:* the target price is set at twice the price distance between entry and stop. This
equals 2R in price terms before costs, matching section 5's example. Net results include the
costs.

**G. Fill prices.**
- **Long:** fills at the ask (bid open of the next candle + that candle's spread). Stop and
  target are checked against the bid.
- **Short:** fills at the bid. Stop and target are checked against the ask (bid + spread).
- **Gaps:** when the next candle opens beyond the stop or target, it fills at the open, not at
  the level.

**H. Same-candle stop and target (9).** *Proposed:* the stop is assumed to come first.

**I. Daily break and windows (6).** Verified XAUUSD sessions run from Sunday 18:00 to Friday
17:00 New York time, with a daily break from 17:00 to 18:00 (00:00 to 01:00 server time,
GMT+2/+3). *Proposed:*
- **Forced close:** 30 minutes before the break (16:30 New York).
- **No new entries** from 60 minutes before the break (16:00 New York) until 60 minutes after
  the reopen (19:00 New York), including the Sunday open.
- **Friday:** same rule, so all positions close before the weekend.
- **Configurable:** set in session terms (New York or server time), not a fixed UTC time.

**J. Bid and ask history (9).**
- **Bars:** MT5 M15 bars are bid prices with a per-bar `spread` field.
- **Ask:** reconstructed as bid + bar spread.
- **Uncertainty:** the bar spread is a single value per bar, and MT5 does not document whether
  it is the minimum or the last spread of the bar. Spread spikes inside a bar may therefore be
  understated.
- **Ticks:** tick history (`get_ticks`) could be used for the entry candle only, at a large cost
  in data volume.
- *Proposed:* bar spread, plus the configured slippage allowance, documented as a limitation.

**K. Maximum spread (8).** *Proposed:* 35 points (USD 0.35), configurable. The current spread
is about 22 points.

**L. Warm-up (8).** *Proposed:* at least 250 completed H1 candles before EMA 200 is used, and 50
completed M15 candles for EMA 20 and ATR 14.

**M. Periods (10).** *Proposed:* a chronological 50 / 25 / 25 split into training, validation
and out-of-sample test. Parameters are fixed after validation; the test period is evaluated
once.

**N. Inputs still needed:**
- XAUUSD commission in GBP per lot, round turn (or 0);
- a slippage assumption in points;
- the backtest period (for example the last 12 months).

**O. News filter (8).** No economic calendar source is integrated, so the filter cannot be
applied. *Proposed:* run without it and state this as a limitation, until a reliable source is
chosen.

**P. Illustrations.** The example charts provided alongside this specification show resistance
zones and an EMA ribbon. These are not part of the written rules and are not implemented.

## Appendix B: what GBP 100 allows on XAUUSD

From the current broker specification (minimum 0.01 lot, step 0.01, loss tick value about
GBP 0.75 per 1.0 lot per USD 0.01, spread about 22 points):

- 0.01 lot loses about **GBP 0.75 for every USD 1** move against it.
- The 2% limit on GBP 100 is **GBP 2**. Stop distance plus spread plus slippage must therefore
  stay within about **USD 2.67**, which leaves about **USD 2.45** of stop distance after the
  spread, before slippage.
- With the stop at the pullback extreme plus 0.2 × ATR(14), most XAUUSD M15 setups are expected
  to need more than this. The backtest will report them as rejected for minimum volume (section
  10), not adjust the rules.
