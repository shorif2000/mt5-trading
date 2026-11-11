# XAUUSD research programme: results summary (2026-11-11)

Branch `research/xauusd-programme`, from `main` at `fe3fceb` (PR #22). Research and offline
backtesting only:
- **no orders were placed, modified or closed**;
- no settings were changed, and Algo Trading was not touched;
- MT5 was used read-only: `terminal_status`, `get_rates`, `get_ticks`, `calc_margin`;
- every experiment was registered before it ran (`docs/research/experiments/`);
- every report records the commit, inputs with sha256, parameters and cost status.

**No strategy here is profitable on the evidence.** 2023–2025 was already viewed, and 2026 is
development evidence. The only clean test, the forward hold-out from trading day 2026-11-16,
has not happened yet.

## Experiments

| Id | What | Report | Outcome (pre-registered rule) |
|---|---|---|---|
| EXP-001 | Break-even exits on the Version 1.0 entries | `EXP-001_f1c41d8ec1.md` | **No variant passes the screen.** The control reproduces all 1,699 Version 1.0 trades exactly. |
| EXP-002 | A event study 2023–24 | `EXP-002_c860443017.md` | Descriptive |
| EXP-003 | A backtest | `EXP-003_c860443017.md` | No floor: **inconclusive**. 0.10R floor: **assumption-dependent**. Both have **insufficient data** in 2025 and 2026. |
| EXP-004 | C event study 2023–24 | `EXP-004_9294d7b6de.md` | Descriptive |
| EXP-005 | C backtest | `EXP-005_9294d7b6de.md` | No floor: **negative**. Floor: **inconclusive**. Both have insufficient data in 2026. |
| EXP-006 | B event study 2023–24 | `EXP-006_806154fa75.md` | Descriptive: 3 events in 2 years |
| EXP-007 | B backtest | `EXP-007_806154fa75.md` | **Insufficient data**: 1 trade in 4 years; the specification is almost never active. |
| (audit) | M1 and tick history | `20261110T2339Z_intrabar_data_audit.md` | Ticks from 2025-06-13; M1 is a rolling window from 2026-07-31 |

## EXP-001: break-even exits (Version 1.0 entries, base scenario)

The stop moves to break-even after a bar closes with the trigger reached, effective from the
next bar's open. Net R per trade (fixed-risk ledger):

| Variant | Training 2023-24 | Validation 2025 | 2026 (dev.) | Gross R/trade (same order) |
|---|---|---|---|---|
| BE-0 (control) | −0.115 | +0.019 | −0.027 | +0.016 / +0.071 / +0.007 |
| BE-0.5 | −0.122 | −0.015 | −0.015 | +0.026 / +0.045 / +0.024 |
| BE-0.75 | −0.114 | +0.003 | −0.003 | +0.028 / +0.060 / +0.034 |
| BE-1.0 | −0.121 | +0.013 | −0.027 | +0.017 / +0.069 / +0.009 |
| BE-1.0+C | −0.133 | +0.014 | −0.034 | +0.010 / +0.070 / +0.002 |

- **Exits that later reached the target:** break-even exits are frequent (BE-0.5: 684 of
  1,699 trades), and about 1 in 4 later reached the original target. Break-even exits add
  £10–78 per period of extra spread and stop slippage.
- **Decision rule:** no variant beats the control's gross R in all three periods, so **none
  passes**. Version 1.0 has no gross edge, so none would be adopted anyway.
- **Ambiguous bars:** 26–288 trigger bars per variant and period also touched the break-even
  level.
  - Managing the stop intrabar with "exit first" assumed in those bars is much worse (e.g.
    BE-0.5 Training −0.262).
  - From 2025-06-14, ticks resolved every such bar: 197, 94, 46 and 59 bars for the four
    variants, with none uncovered.
  - On ticks, intrabar management comes out close to the bar-close rule (BE-0.5 −0.020
    against −0.022), so the pessimistic ordering overstates the damage.
- **Tick timing check:** 241 of 245 tick-resolved bars match the M15 bar's high and low
  exactly. The 4 small differences (≤ $0.16) are in late June 2025, where ticks are about 10
  times sparser.

## Strategies A, C and B (fixed risk, base scenario, news filter on)

| Strategy, arm | Trades (T / V / 2026) | Gross R/trade (T / V / 2026) | Net R/trade (T / V / 2026) | Pooled net R [95% CI] | Classification |
|---|---|---|---|---|---|
| A, no floor | 200 / 67 / 55 | −0.001 / +0.009 / +0.083 | −0.119 / −0.062 / +0.040 | −0.080 [−0.208, +0.059] | inconclusive; insufficient data (V, 2026) |
| A, 0.10R floor | 38 / 42 / 49 | −0.041 / +0.079 / +0.033 | −0.092 / +0.032 / −0.005 | −0.018 [−0.230, +0.205] | assumption-dependent; insufficient data (V, 2026) |
| C, no floor | 198 / 91 / 54 | −0.056 / −0.022 / −0.254 | −0.155 / −0.076 / −0.293 | −0.156 [−0.277, −0.031] | **negative**; insufficient data (2026) |
| C, 0.10R floor | 63 / 70 / 53 | +0.033 / +0.052 / −0.293 | −0.012 / +0.011 / −0.332 | −0.094 [−0.259, +0.076] | inconclusive; insufficient data (2026) |
| B, no floor | 1 / 0 / 0 | +1.502 / – / – | +1.418 / – / – | one trade | insufficient data |
| B, 0.10R floor | 0 / 0 / 0 | – | – | – | insufficient data |

- **Few large wins:** without the best 10 trades, every A and C arm has a negative sum of R
  (A −45.0 and −21.6; C −72.5 and −36.7).
- **Entry-slippage stress (40-point scenario):** every A and C arm is negative.
- **A (event study):**
  - 554 breakout events in 2023–24; 239 failed back into the range and 229 reached a signal.
  - Before costs, within 16 bars, −1R came first 112 times and +2R first only 47 times.
- **C (event study):**
  - 1,176 events; 463 invalidated, 155 were displacements rather than sweeps, 265 reached a
    signal.
  - Before costs, −1R came first 105 times and +2R first 28 times.
- **B:**
  - Valid ranges exist in only 29 H1 hours of 2022–2026.
  - My break-lockout clarification removes about two-thirds of candidate hours. Even
    without it, only 65 hours qualify: the binding constraint is the specified "two separate
    tests of *each* boundary" combined with ADX below 20.
  - The specification, as written, cannot be evaluated. Changing it would be a new
    registered experiment, not a repair.

## Cost sensitivity

- **The 0.10R floor:**
  - It removes most signals with tight stops: A Training 200 trades down to 38; C 198 down
    to 63.
  - It raises the average stop distance, cutting cost per trade from about 0.12R to 0.05R
    (A Training).
  - It improves net R in both the A and C Training periods, but no arm becomes positive
    across periods.
  - Consistent with the diagnostic review, **cost relative to stop size** is the main
    drag, and gross edge is about zero.
- **What's measured and what's assumed:**
  - Spread: measured, from historical bars.
  - Stop slippage: measured percentiles from the account's own stop fills.
  - Entry and market-exit slippage: assumed scenarios (0, 7 and 40 points).
  - Commission: £0, measured.
  - Swap: 0, because no position is held overnight.
- **Full grids:** each report has the full 9-scenario grid.

## News calendar

- **`config/economic_calendar.yaml`** (official sources only):
  - 34 FOMC statements, 2022-11-02 to 2026-10-28. Each time was read from its own
    federalreserve.gov release page, with EDT/EST checked against daylight saving. This
    includes the 2025-08-22 notation-vote statement at 10:00.
  - 9 future meetings, dated only, each blocking its whole New York day.
- **Fail closed:** an entry outside verified coverage is rejected. Tests cover the window
  edges, daylight saving, unpublished times and an unsourced event type.
- **Impact:** 0 signals excluded in every A, C and B run. FOMC is at 14:00 New York. A enters
  only until 11:00, and C's latest entries rarely fall in 13:30–14:15. The news-on and
  news-off results are identical.
- **Blocker:** CPI and Employment Situation dates are **not sourced**. bls.gov returns HTTP 403
  to automated requests, site-wide. Making requests look like a browser to get past that was
  declined.
  - Amendment 2 records that the news-on arms filter FOMC only.
  - To close the gap: save the BLS pages from a browser into `data/calendar/raw/bls/`, or
    authorise a request that identifies itself with contact details. Then rebuild the
    calendar and repeat the runs under new ids.

## M1 and tick history

- **Bridge:** the earlier "port in use" errors came from duplicate launches while the running
  bridge (wineserver, port 18812) was still serving. Nothing was killed or restarted.
- **Ticks:** bid and ask from **2025-06-13 06:18 UTC**, about 12–14 per second. 1,094 of 1,116
  daily samples had a tick within 2 minutes; the misses are holidays and the days before the
  start. June 2025 is thinner than later months.
- **M1:** a rolling window of about 100,000 bars, starting **2026-07-31**, with one Labor Day
  gap.
- **Time labels:** the MCP server labels summer timestamps one hour late, because it converts
  with today's offset. Research code converts raw broker time itself.
- **For break-even research:** Training 2023–24 can't be resolved intrabar. From June 2025
  onwards, ticks are sufficient.

## Checks

- `uv run pytest`: all tests pass, including the new break-even, news-filter and candidate
  tests.
- `uv run ruff check .`: clean.
- `uv run mypy src`: clean.
- `git diff --check`: clean.
- Every run used `--require-clean`.
- The EXP-001 control reconciles with Version 1.0 exactly.

## Limitations and open items

1. All history is viewed or development evidence. No result is out of sample.
2. Validation 2025 and 2026 have fewer than 100 events for A, and 2026 for C. B has almost
   none.
3. The news filter is partial: FOMC only.
4. Entry slippage is unknown. There is one spread value per M15 bar, and the stop is assumed
   first within a bar.
5. Margin uses today's leverage. Fixed-risk R uses the risk engine's sizing estimate.

## Recommendation

- **Don't adopt any strategy or exit rule.** No break-even variant passes. C without the floor
  is negative. A and C with the floor are inconclusive, and their gross expectancy is near
  zero.
- **The one direction worth more time is a forward test of strategy A:**
  - both arms, exactly as registered, from trading day 2026-11-16;
  - read-only, with no changes;
  - A is the least negative of the candidates, and it is close to zero before costs.
  - Expect a year or more to reach 100 events, and judge it only by the pre-registered rule.
- **In parallel, measure entry slippage** on a demo account. Every result depends on that
  assumption, and on cost relative to stop distance more than on the signal itself.
- **Any new hypothesis** (for example, setups with structurally wider stops so that costs are a
  smaller share of R) must be specified and registered first, and must show a gross edge
  before costs, not just a better net.
