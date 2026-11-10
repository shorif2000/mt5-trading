# XAUUSD trend-pullback: strategy specification (proposal for review)

**Status: PROPOSED, NOT APPROVED.** This is a research hypothesis, not a validated or
profitable strategy. Nothing in it is implemented. Each parameter marked *(proposed)* needs
your approval before the backtest engine is built or run. All parameters will be configurable,
and results must be judged out of sample.

## 1. Account and constraints

| Item | Value |
|---|---|
| Instrument | `XAUUSD` only (broker symbol verified; `XAUUSD.crp` excluded) |
| Data | Read-only MT5 history and specifications from the current account; no orders |
| Paper account | Virtual ledger, starting at **GBP 100**, updated by each closed simulated trade |
| Risk per trade | At most **2 % of the paper ledger balance**, recalculated per signal (PR #13 rules) |
| Volume | Broker minimum 0.01 lot and step 0.01; never reduced or relaxed |
| Margin | MT5 `calc_margin` for the exact side, volume and price (PR #14), against paper figures |
| Positions | One XAUUSD position at a time |

**What GBP 100 means for gold.** Figures are from the current specification (tick value about
GBP 0.75 per 1.0 lot per 0.01 USD, spread about 22 points):
- 0.01 lot loses about **GBP 0.75 for every USD 1 move against it**.
- The 2 % limit is **GBP 2**, so stop distance plus spread plus slippage must be at most
  **about USD 2.67**.
- The stop can therefore be at most about **USD 2.45** from the entry (USD 2.67 minus the USD
  0.22 spread), before any slippage allowance.

Most H1-scale gold setups need wider stops, so many signals are expected to be rejected by
risk management. The backtest reports this as it is; the rules are not loosened to produce
more trades.

## 2. Timeframes and completed bars

- **H4:** trend context. **H1:** pullback setup. **M15:** entry confirmation.
- Only completed bars are used (the existing ingest rules). A signal at the close of an M15 bar
  can be filled at the earliest at the **open of the next M15 bar**.
- Timestamps are UTC, converted with the DST-aware broker clock. Sessions follow
  `config/market_sessions.yaml`: gold runs Sunday 18:00 to Friday 17:00 New York time, with a
  daily break from 17:00 to 18:00.

## 3. Trend identification (H4) *(proposed)*

- **Uptrend:** EMA(50) > EMA(200) on H4 closes, the last H4 close is above EMA(50), and EMA(50)
  has risen over the last 5 H4 bars.
- **Downtrend:** the mirror image.
- **Otherwise:** no trade.
- **Warm-up:** at least 250 completed H4 bars before any signal, or no signal is produced.

## 4. Pullback (H1) *(proposed)*

In an uptrend (mirrored for a downtrend):
- A completed H1 bar's low comes within 0.25 × ATR(14, H1) of the H1 EMA(20), or below it.
- The H1 close stays above the H1 EMA(50), so the pullback hasn't broken the structure.
- The pullback starts from a swing high no more than 12 H1 bars old.
- The pullback setup stays valid for at most 4 H1 bars; after that it expires.

## 5. Entry confirmation (M15) *(proposed)*

While a pullback setup is valid:
- **Long trigger:** a completed M15 bar closes above the high of the previous completed M15
  bar and above the M15 EMA(20).
- **Short trigger:** the mirror image.
- **Entry:** a market order at the next M15 bar open, at the **ask for a buy** (bid open +
  that bar's MT5 spread) or the **bid for a sell**.

## 6. Stop loss *(proposed)*

- **Long:** below the lowest low of the last 8 completed M15 bars, minus a buffer of
  max(current spread, 0.1 × ATR(14, M15)). **Short:** the mirror image.
- The stop must satisfy the broker stops level, measured from the price that closes the
  position (PR #13).
- If the stop distance plus costs exceeds the 2 % limit at the 0.01 minimum, the signal is
  **rejected by risk management**. The stop is never moved closer just to make a trade fit.

## 7. Take profit and exits *(proposed)*

Exits, in priority order:
1. **Stop loss**, hit by the bar's adverse extreme. Buys close at the bid; sells close at the
   ask (bid + bar spread).
2. **Take profit at 2R**, where R is the planned loss distance including spread.
3. **Trend failure:** an H1 close beyond the H1 EMA(50) against the position, closed at the
   next M15 open.
4. **Time exit:** see section 8.

When the stop and the take profit fall inside the same M15 bar, the **stop is assumed to come
first** (the pessimistic case).

## 8. Holding period and overnight positions *(proposed)*

- **No overnight positions.** Every position is closed by **16:45 New York time**, before gold's
  17:00 daily break and the rollover. No new entries after 16:00 New York.
- **Reasons:**
  - **Swap:** gold's long swap is −69 points, about GBP 0.52 per 0.01 lot per night (26 % of the
    GBP 2 limit). Triple swap on Wednesdays makes it worse.
  - **Price gaps:** the reopen after the break can jump past the stop.
- **Maximum holding period:** 8 hours.
- If overnight holding is approved later, `holding_nights` must be set, so swap is included in
  the loss estimate (PR #13).

## 9. When not to trade *(proposed)*

- Spread above 35 points on the signal bar or the entry bar.
- The first 60 minutes after the daily reopen (18:00–19:00 New York) and after the Sunday open.
- Friday after 12:00 New York.
- Any date flagged in `market_sessions.yaml` as a confirmed closure, or as an *unconfirmed*
  placeholder.
- Missing or gapped data in the bars used for the decision (the ingest gap rules).
- An XAUUSD position already open in the paper account.
- **High-impact US economic releases (30 minutes before and after):** no economic calendar
  source is integrated, so this filter **cannot be applied yet**. Until a source is supplied,
  the results state this as a limitation.

## 10. Costs in results

| Cost | Treatment |
|---|---|
| Spread | Each MT5 bar's own `spread` field. Buys fill at the ask; sell stops and targets trigger and fill at the ask |
| Slippage | `config/risk.yaml` `slippage_points` (must be set), applied adversely at entry and exit |
| Commission | `config/risk.yaml` `commission_per_lot_round_turn` in GBP (must be set; 0 if the account has none) |
| Swap | Not incurred while overnight holding is disallowed; otherwise the swap model from PR #13 |
| Currency | USD P/L converted to GBP with **GBPUSD bars at the exit time**, not today's tick value. Sizing uses the tick value converted at the signal time |

Results are reported both gross and net of each cost, so their effect is visible.

## 11. Backtest outcome categories

Every signal is recorded in exactly one final category:

1. **Signal generated:** trend, pullback and confirmation conditions met. Every candidate is
   counted, including those filtered by section 9 (counted separately, with the reason).
2. **Rejected by risk management:** the 0.01 minimum would lose more than 2 % of the paper
   balance, or any sizing rule failed. The would-be minimum-volume loss is recorded to show the
   size of the shortfall.
3. **Rejected by margin:** sized within risk, but MT5 margin was unavailable, or free margin or
   the margin level was insufficient. Margin comes from read-only `calc_margin` at the signal's
   entry price.
4. **Executable:** passed risk and margin at the permitted volume (at least the 0.01 minimum).
   Only these are simulated, and they update the paper ledger.

The 2 % limit and the broker minimum volume are never relaxed to increase category 4.

## 12. Validation and reporting

- **Split:** the history is split chronologically. Parameters are fixed on the first 70 % (in
  sample) and evaluated once on the last 30 % (out of sample). No tuning on out-of-sample data.
- **Reported:**
  - counts per category and rejection reason;
  - executable trades with entry, exit, volume, costs and net P/L in GBP;
  - win rate, average R, expectancy in R and GBP;
  - maximum drawdown of the paper ledger, and the final balance.
- No claim of profitability. With few executable trades, results are reported as statistically
  inconclusive.

## 13. Data and engine requirements (for the implementation PR)

- **History collection:** read-only `get_rates` range requests, because one request is capped
  at 5,000 bars (about 52 trading days of M15). The collector needs a range mode for history;
  it is still read-only.
- **Margin:** one `calc_margin` call per sized signal (live, read-only). A backtest therefore
  needs the terminal connected, but places no orders.
- **Determinism:** the same history and parameters give the same results.

## 14. Decisions needed from you

1. Approve or change each *(proposed)* parameter in sections 3 to 9.
2. Confirm **no overnight positions** and the **16:45 New York** forced exit.
3. Provide commission (GBP per lot, round turn, or 0) and a slippage assumption in points for
   XAUUSD.
4. Choose the backtest period, for example the last 12 months of M15 history.
5. Decide whether to supply an economic calendar source for the news filter, or accept it as a
   stated limitation.
