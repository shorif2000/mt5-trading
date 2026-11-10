# XAUUSD M15 Trend Pullback, Version 1.1: real-yield direction filter

**Status:** approved by the account owner on 2026-11-10 with the recommended defaults (open
points in section 7, decisions recorded there). Research and backtesting only.
Version 1.0 (`docs/strategy-xauusd-trend-pullback.md`) stays the approved strategy and the
baseline. Research and backtesting only; no execution.

## 1. Change from Version 1.0

Version 1.1 adds one rule to section 3 (entry conditions). Every other rule, parameter, cost and
risk limit is unchanged from Version 1.0 with amendment 1.

**Hypothesis (unvalidated):** gold tends to move inversely to US 10-year real yields, so H1
trend-continuation entries that agree with the recent direction of real yields may perform
better than those that oppose it. This is a research hypothesis, not established evidence.

**Rule.** At each candidate entry, compute the real-yield change

    delta = R(latest available) - R(L business days earlier)

where `R` is FRED series `DFII10` (10-year TIPS constant-maturity yield, percent, daily, H.15).

| Real-yield regime | Condition | Longs | Shorts |
|---|---|---|---|
| Falling | delta <= -threshold | allowed | rejected |
| Rising | delta >= +threshold | rejected | allowed |
| Neutral | otherwise | allowed | allowed |

Rejected entries are counted with the reason `real-yield filter` (section 10 reporting).
The filter only gates new entries; open positions are managed exactly as in Version 1.0.

## 2. Data timing (no look-ahead)

- FRED's `DFII10` observation for date D is published with the H.15 daily update on the next
  business day. Evidence on 2026-11-10: the latest observation was 2026-11-09 and FRED's
  `last_updated` was 2026-11-10 15:16 US Central (16:16 New York).
- **Availability rule:** the observation for D may be used from **17:00 New York on the next
  US business day after D** (the next gold session open after publication). Before that, the
  previous observation is the latest available.
- FRED marks non-business days with `"."`. These are skipped, never filled or interpolated.
  `L` counts published observations, not calendar days.
- If the latest available observation is more than 5 business days old, new entries are
  rejected with the reason `real-yield data stale`.

## 3. Data provenance

- Downloaded once through the read-only FRED MCP server into a git-ignored local file, with
  the series id, FRED `last_updated` and retrieval time. Its sha256 is recorded in each
  backtest report, as for the MT5 history.
- **Vintage limitation:** the FRED MCP tools return only the current vintage (no real-time
  period parameters). Market yields in H.15 are rarely revised, but this cannot be verified
  through this connection, so the report must state it.
- `config/provenance.yaml` gains the `fred` MCP server (read-only, research data).

## 4. Parameters (configurable)

| Parameter | Proposed default | Notes |
|---|---|---|
| `lookback_days` (L) | 20 business days | about one month |
| `threshold_pct` | 0.10 (10 basis points) | |
| `neutral_behaviour` | allow both | decision 3 |
| `stale_after_days` | 5 business days | |

## 5. Test protocol

1. **Fixed a priori:** the defaults above are set before any Version 1.1 result is seen and are
   not tuned (decision 2).
2. Same periods, history, costs, scenarios, starting balance and sizing as report
   `20261110T222100Z_7f525aace4`. Report Version 1.0 and Version 1.1 side by side, plus the
   trades the filter removed and their Version 1.0 result.
3. **Contamination caveat:** the 2026 Out-of-sample period has already been viewed in
   Version 1.0 reports. Version 1.1 out-of-sample results are therefore not blind and must be
   reported as weaker evidence than a genuinely unseen period.
4. Fewer trades are expected. If the filtered sample is too small, the result is reported as
   inconclusive (section 10 of Version 1.0).

## 6. Alternatives considered, not proposed

- **Broad dollar index (`DTWEXBGS`):** the H.10 release is published weekly, so daily values
  arrive up to about a week late. That adds look-ahead risk and weakens timeliness.
- **Policy rate (`EFFR`/`DFF`) or monthly data (`CPIAUCSL`, `UNRATE`):** these change too rarely
  to matter for intraday entries. Their release *times* would belong in a news filter, which
  FRED does not provide through this connection.
- **Combining several macro filters:** more degrees of freedom on a small sample; one filter
  first.

## 7. Owner decisions (2026-11-10)

1. Hypothesis and rule in section 1: approved.
2. Parameters: fixed defaults, no tuning.
3. Neutral regime: both directions allowed.
4. Lookback 20 business days, threshold 10 basis points: approved.
5. Out-of-sample contamination: accepted as a stated caveat of the draft as approved; results
   on that period are reported as weaker evidence.
