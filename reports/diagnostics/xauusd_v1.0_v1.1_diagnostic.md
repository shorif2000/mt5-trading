# XAUUSD Version 1.0 and 1.1: diagnostic review of the backtests

Research and diagnosis only. No strategy rule, parameter or risk setting was changed; no MT5 access was made (the review reads committed manifests and the local history file).

## Inputs

- Version 1.0: `reports/backtests/20261110T222100Z_7f525aace4.json` (commit `7f525aace4`), base scenario `entry stop-median-proxy (7 pts, SCENARIO) / stop exits p90 (40 pts, evidence) / sizing allowance 67 pts`.
- Version 1.1: `reports/backtests/20261110T223948Z_9caf03ac73.json` (commit `9caf03ac73`), base scenario `entry stop-median-proxy (7 pts, SCENARIO) / stop exits p90 (40 pts, evidence) / sizing allowance 67 pts`.
- History: `data/history/xauusd_backtest.local.json` sha256 `e3b35038566b61b5…`, matching both runs.
- Script: `scripts/xauusd_diagnostics.py` (bootstrap seed 20261110). Sessions use New York time, as the approved reports do.
- **2026 is development evidence, not out-of-sample**: it was examined during Version 1.1 design. Labelled “2026 (development)” below.

**Units.** The paper ledger compounds (2% of a falling balance), so GBP totals mostly reflect the balance path. Comparisons below use **R**: each trade's net result divided by its estimated loss at sizing (the risk the sizing rules accepted). −1R is a full planned loss. GBP is shown where the task asks for it.

## 1. Trade expectancy

| Ver | Period | Trades | Win rate | Avg win | Avg loss | Win/loss (R) | Expectancy | Gross profit / loss | PF | Max cons. W / L | Hold median / mean (min) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1.0 | Training 2023-24 | 823 | 33.9% | £7.76 / +1.31R | £-5.45 / -0.85R | 1.55 | £-0.97 / -0.115R | £2,166 / £2,966 | 0.73 | 5 / 14 | 120 / 172 |
| 1.0 | Validation 2025 | 498 | 39.8% | £23.12 / +1.38R | £-15.02 / -0.88R | 1.57 | £+0.14 / +0.019R | £4,577 / £4,506 | 1.02 | 6 / 15 | 150 / 220 |
| 1.0 | 2026 (development) | 378 | 35.2% | £22.13 / +1.55R | £-12.93 / -0.88R | 1.75 | £-0.59 / -0.027R | £2,943 / £3,167 | 0.93 | 5 / 14 | 120 / 195 |
| 1.1 | Training 2023-24 | 636 | 33.3% | £9.83 / +1.27R | £-6.81 / -0.86R | 1.47 | £-1.26 / -0.151R | £2,084 / £2,887 | 0.72 | 5 / 18 | 120 / 170 |
| 1.1 | Validation 2025 | 373 | 38.9% | £21.54 / +1.39R | £-13.86 / -0.88R | 1.58 | £-0.10 / +0.003R | £3,124 / £3,161 | 0.99 | 6 / 15 | 135 / 205 |
| 1.1 | 2026 (development) | 299 | 35.5% | £23.82 / +1.58R | £-13.42 / -0.88R | 1.79 | £-0.22 / -0.010R | £2,525 / £2,590 | 0.98 | 5 / 11 | 120 / 191 |

Reconciliation against the committed reports (trades, net, profit factor, win rate, maximum consecutive losses, mean holding time):

- Version 1.0, Training 2023-24: all match the report
- Version 1.0, Validation 2025: all match the report
- Version 1.0, 2026 (development): all match the report
- Version 1.1, Training 2023-24: all match the report
- Version 1.1, Validation 2025: all match the report
- Version 1.1, 2026 (development): all match the report

With a 2R target, break-even needs a win rate of about 1 / (1 + win/loss ratio). The realised win/loss ratio is well under 2 because of costs, forced closes and trend exits (section 4), so the break-even win rate is higher than the 33% a clean 2R would need.

## 2. Trading sessions

Sessions by entry time in New York time. The approved report definition is used: Asia 19:00-03:00, London 03:00-08:00, New York 08:00-17:00. The New York window is split at 12:00 into the London/New York overlap (08:00-12:00, an analysis convention, not an approved definition) and the New York afternoon. No entries are allowed 16:00-19:00.

| Ver | Period | Session | Trades | Win rate | Mean R [95% CI] | Sum R | PF (R) | Max DD (R) |
|---|---|---|---|---|---|---|---|---|
| 1.0 | Training 2023-24 | Asia 19-03 | 417 | 33.3% | -0.095 [-0.20, +0.02] | -39.4 | 0.85 | 55.2 |
| 1.0 | Training 2023-24 | London 03-08 | 183 | 25.7% | -0.275 [-0.43, -0.11] | -50.3 | 0.59 | 50.3 |
| 1.0 | Training 2023-24 | London/NY overlap 08-12 | 107 | 45.8% | +0.049 [-0.14, +0.25] | 5.2 | 1.11 | 7.5 |
| 1.0 | Training 2023-24 | New York afternoon 12-17 | 116 | 37.9% | -0.089 [-0.21, +0.03] | -10.3 | 0.70 | 14.5 |
| 1.0 | Validation 2025 | Asia 19-03 | 258 | 34.9% | +0.003 [-0.15, +0.16] | 0.8 | 1.01 | 27.3 |
| 1.0 | Validation 2025 | London 03-08 | 100 | 39.0% | +0.036 [-0.21, +0.29] | 3.6 | 1.06 | 7.8 |
| 1.0 | Validation 2025 | London/NY overlap 08-12 | 85 | 45.9% | +0.004 [-0.19, +0.22] | 0.3 | 1.01 | 8.6 |
| 1.0 | Validation 2025 | New York afternoon 12-17 | 55 | 54.5% | +0.090 [-0.10, +0.27] | 4.9 | 1.38 | 2.7 |
| 1.0 | 2026 (development) | Asia 19-03 | 176 | 33.5% | -0.024 [-0.22, +0.18] | -4.3 | 0.96 | 19.3 |
| 1.0 | 2026 (development) | London 03-08 | 82 | 24.4% | -0.290 [-0.54, -0.02] | -23.8 | 0.59 | 28.0 |
| 1.0 | 2026 (development) | London/NY overlap 08-12 | 51 | 41.2% | +0.277 [-0.07, +0.64] | 14.1 | 1.60 | 5.0 |
| 1.0 | 2026 (development) | New York afternoon 12-17 | 69 | 47.8% | +0.053 [-0.14, +0.25] | 3.7 | 1.17 | 5.0 |
| 1.1 | Training 2023-24 | Asia 19-03 | 313 | 30.7% | -0.163 [-0.28, -0.03] | -51.1 | 0.75 | 54.3 |
| 1.1 | Training 2023-24 | London 03-08 | 145 | 24.8% | -0.285 [-0.46, -0.11] | -41.3 | 0.58 | 42.9 |
| 1.1 | Training 2023-24 | London/NY overlap 08-12 | 94 | 47.9% | +0.040 [-0.15, +0.24] | 3.8 | 1.10 | 10.0 |
| 1.1 | Training 2023-24 | New York afternoon 12-17 | 84 | 41.7% | -0.088 [-0.23, +0.06] | -7.4 | 0.71 | 10.1 |
| 1.1 | Validation 2025 | Asia 19-03 | 198 | 34.8% | +0.005 [-0.17, +0.18] | 0.9 | 1.01 | 25.7 |
| 1.1 | Validation 2025 | London 03-08 | 70 | 35.7% | -0.062 [-0.37, +0.23] | -4.3 | 0.90 | 10.5 |
| 1.1 | Validation 2025 | London/NY overlap 08-12 | 62 | 46.8% | +0.021 [-0.24, +0.29] | 1.3 | 1.05 | 9.2 |
| 1.1 | Validation 2025 | New York afternoon 12-17 | 43 | 51.2% | +0.072 [-0.16, +0.31] | 3.1 | 1.27 | 2.5 |
| 1.1 | 2026 (development) | Asia 19-03 | 138 | 33.3% | -0.018 [-0.25, +0.22] | -2.5 | 0.97 | 17.9 |
| 1.1 | 2026 (development) | London 03-08 | 65 | 21.5% | -0.366 [-0.61, -0.07] | -23.8 | 0.50 | 25.8 |
| 1.1 | 2026 (development) | London/NY overlap 08-12 | 43 | 44.2% | +0.340 [-0.06, +0.75] | 14.6 | 1.76 | 5.3 |
| 1.1 | 2026 (development) | New York afternoon 12-17 | 53 | 50.9% | +0.165 [-0.06, +0.39] | 8.7 | 1.64 | 2.1 |

## 3. Market regimes at entry

Measured at the signal close from completed bars only:

- **Trend strength**: (H1 EMA50 − EMA200) in the trade direction ÷ H1 ATR(14).
- **Range-bound vs directional**: H1 efficiency ratio over the last 20 completed H1 bars (net move ÷ path length; low = choppy).
- **Volatility**: M15 ATR(14) ÷ median M15 ATR over the previous 960 M15 bars (about 10 trading days).

Tercile cut-offs come from Version 1.0 Training trades only and are applied unchanged to every other period and to Version 1.1.

- Trend strength cut-offs: 1.96 and 4.13
- H1 efficiency cut-offs: 0.12 and 0.26
- Volatility cut-offs: 0.76 and 1.06

### Trend strength

| Ver | Period | Bucket | Trades | Win rate | Mean R [95% CI] | Sum R | PF (R) | Max DD (R) |
|---|---|---|---|---|---|---|---|---|
| 1.0 | Training 2023-24 | weak | 274 | 32.8% | -0.127 [-0.26, +0.00] | -34.9 | 0.77 | 41.3 |
| 1.0 | Training 2023-24 | medium | 274 | 38.7% | -0.028 [-0.16, +0.11] | -7.7 | 0.95 | 27.5 |
| 1.0 | Training 2023-24 | strong | 275 | 30.2% | -0.190 [-0.32, -0.05] | -52.2 | 0.68 | 53.4 |
| 1.0 | Validation 2025 | weak | 132 | 40.2% | +0.055 [-0.15, +0.25] | 7.3 | 1.11 | 11.8 |
| 1.0 | Validation 2025 | medium | 187 | 38.5% | -0.006 [-0.18, +0.17] | -1.2 | 0.99 | 21.8 |
| 1.0 | Validation 2025 | strong | 179 | 40.8% | +0.020 [-0.16, +0.20] | 3.6 | 1.04 | 8.5 |
| 1.0 | 2026 (development) | weak | 156 | 36.5% | +0.040 [-0.14, +0.24] | 6.2 | 1.07 | 11.1 |
| 1.0 | 2026 (development) | medium | 140 | 37.1% | -0.011 [-0.21, +0.18] | -1.6 | 0.98 | 13.7 |
| 1.0 | 2026 (development) | strong | 82 | 29.3% | -0.181 [-0.45, +0.09] | -14.8 | 0.73 | 18.0 |
| 1.1 | Training 2023-24 | weak | 208 | 31.7% | -0.189 [-0.33, -0.04] | -39.2 | 0.67 | 40.4 |
| 1.1 | Training 2023-24 | medium | 205 | 38.5% | -0.048 [-0.19, +0.10] | -9.8 | 0.91 | 24.9 |
| 1.1 | Training 2023-24 | strong | 223 | 30.0% | -0.211 [-0.35, -0.07] | -47.1 | 0.65 | 51.9 |
| 1.1 | Validation 2025 | weak | 93 | 36.6% | -0.011 [-0.24, +0.23] | -1.1 | 0.98 | 12.3 |
| 1.1 | Validation 2025 | medium | 139 | 38.8% | -0.015 [-0.21, +0.18] | -2.1 | 0.97 | 23.5 |
| 1.1 | Validation 2025 | strong | 141 | 40.4% | +0.029 [-0.17, +0.23] | 4.1 | 1.05 | 9.4 |
| 1.1 | 2026 (development) | weak | 116 | 38.8% | +0.127 [-0.10, +0.37] | 14.8 | 1.25 | 8.7 |
| 1.1 | 2026 (development) | medium | 119 | 36.1% | -0.028 [-0.24, +0.18] | -3.3 | 0.95 | 13.1 |
| 1.1 | 2026 (development) | strong | 64 | 28.1% | -0.224 [-0.52, +0.07] | -14.4 | 0.67 | 15.9 |

### H1 efficiency

| Ver | Period | Bucket | Trades | Win rate | Mean R [95% CI] | Sum R | PF (R) | Max DD (R) |
|---|---|---|---|---|---|---|---|---|
| 1.0 | Training 2023-24 | range-bound | 274 | 32.1% | -0.156 [-0.28, -0.03] | -42.7 | 0.72 | 51.8 |
| 1.0 | Training 2023-24 | mixed | 274 | 35.4% | -0.091 [-0.22, +0.04] | -24.9 | 0.83 | 27.9 |
| 1.0 | Training 2023-24 | directional | 275 | 34.2% | -0.099 [-0.23, +0.04] | -27.2 | 0.83 | 38.0 |
| 1.0 | Validation 2025 | range-bound | 148 | 39.9% | -0.025 [-0.21, +0.16] | -3.7 | 0.95 | 19.0 |
| 1.0 | Validation 2025 | mixed | 145 | 39.3% | +0.027 [-0.17, +0.22] | 4.0 | 1.05 | 19.0 |
| 1.0 | Validation 2025 | directional | 205 | 40.0% | +0.046 [-0.13, +0.22] | 9.4 | 1.09 | 16.7 |
| 1.0 | 2026 (development) | range-bound | 119 | 26.1% | -0.281 [-0.48, -0.08] | -33.5 | 0.57 | 39.1 |
| 1.0 | 2026 (development) | mixed | 121 | 41.3% | +0.129 [-0.10, +0.36] | 15.6 | 1.26 | 9.9 |
| 1.0 | 2026 (development) | directional | 138 | 37.7% | +0.056 [-0.16, +0.27] | 7.7 | 1.10 | 10.4 |
| 1.1 | Training 2023-24 | range-bound | 214 | 29.9% | -0.213 [-0.35, -0.07] | -45.5 | 0.64 | 52.2 |
| 1.1 | Training 2023-24 | mixed | 214 | 36.9% | -0.098 [-0.25, +0.05] | -21.0 | 0.82 | 21.4 |
| 1.1 | Training 2023-24 | directional | 208 | 33.2% | -0.142 [-0.29, +0.01] | -29.6 | 0.76 | 32.3 |
| 1.1 | Validation 2025 | range-bound | 111 | 40.5% | -0.001 [-0.20, +0.21] | -0.1 | 1.00 | 11.1 |
| 1.1 | Validation 2025 | mixed | 108 | 37.0% | -0.033 [-0.26, +0.20] | -3.6 | 0.94 | 22.8 |
| 1.1 | Validation 2025 | directional | 154 | 39.0% | +0.030 [-0.16, +0.23] | 4.6 | 1.06 | 16.1 |
| 1.1 | 2026 (development) | range-bound | 91 | 24.2% | -0.305 [-0.52, -0.06] | -27.7 | 0.54 | 34.9 |
| 1.1 | 2026 (development) | mixed | 89 | 42.7% | +0.157 [-0.10, +0.44] | 14.0 | 1.32 | 8.2 |
| 1.1 | 2026 (development) | directional | 119 | 38.7% | +0.091 [-0.13, +0.32] | 10.8 | 1.16 | 9.6 |

### Volatility

| Ver | Period | Bucket | Trades | Win rate | Mean R [95% CI] | Sum R | PF (R) | Max DD (R) |
|---|---|---|---|---|---|---|---|---|
| 1.0 | Training 2023-24 | low | 274 | 31.8% | -0.149 [-0.28, -0.01] | -40.9 | 0.76 | 54.8 |
| 1.0 | Training 2023-24 | normal | 274 | 36.5% | -0.036 [-0.17, +0.11] | -10.0 | 0.93 | 17.6 |
| 1.0 | Training 2023-24 | high | 275 | 33.5% | -0.160 [-0.27, -0.04] | -43.9 | 0.68 | 45.4 |
| 1.0 | Validation 2025 | low | 103 | 30.1% | -0.195 [-0.42, +0.04] | -20.0 | 0.70 | 25.4 |
| 1.0 | Validation 2025 | normal | 179 | 43.6% | +0.210 [+0.02, +0.40] | 37.6 | 1.42 | 6.8 |
| 1.0 | Validation 2025 | high | 216 | 41.2% | -0.036 [-0.18, +0.12] | -7.9 | 0.93 | 24.5 |
| 1.0 | 2026 (development) | low | 102 | 32.4% | -0.053 [-0.30, +0.20] | -5.4 | 0.91 | 12.1 |
| 1.0 | 2026 (development) | normal | 155 | 36.8% | +0.004 [-0.19, +0.21] | 0.6 | 1.01 | 17.6 |
| 1.0 | 2026 (development) | high | 121 | 35.5% | -0.045 [-0.25, +0.16] | -5.4 | 0.92 | 13.8 |
| 1.1 | Training 2023-24 | low | 212 | 29.7% | -0.195 [-0.35, -0.04] | -41.3 | 0.70 | 48.6 |
| 1.1 | Training 2023-24 | normal | 206 | 36.4% | -0.051 [-0.21, +0.10] | -10.6 | 0.91 | 19.3 |
| 1.1 | Training 2023-24 | high | 218 | 33.9% | -0.203 [-0.32, -0.08] | -44.2 | 0.60 | 45.2 |
| 1.1 | Validation 2025 | low | 81 | 29.6% | -0.184 [-0.45, +0.09] | -14.9 | 0.72 | 23.5 |
| 1.1 | Validation 2025 | normal | 135 | 41.5% | +0.178 [-0.03, +0.40] | 24.1 | 1.35 | 6.8 |
| 1.1 | Validation 2025 | high | 157 | 41.4% | -0.052 [-0.22, +0.11] | -8.2 | 0.90 | 21.5 |
| 1.1 | 2026 (development) | low | 73 | 34.2% | +0.035 [-0.28, +0.34] | 2.5 | 1.06 | 8.2 |
| 1.1 | 2026 (development) | normal | 120 | 37.5% | +0.014 [-0.20, +0.23] | 1.7 | 1.03 | 14.2 |
| 1.1 | 2026 (development) | high | 106 | 34.0% | -0.068 [-0.29, +0.16] | -7.2 | 0.88 | 14.7 |

## 4. Entries and exits

| Ver | Period | Entry − EMA20 (ATR, median) | M15 ATR (median) | Stop distance (median, $ / ATR) | Stops | Targets | Forced close | Trend exit | Mean R at target | Mean R at stop |
|---|---|---|---|---|---|---|---|---|---|---|
| 1.0 | Training 2023-24 | 0.59 | $1.74 | $3.29 / 1.96 | 56% | 25% | 16% | 2% | +1.60 | -0.94 |
| 1.0 | Validation 2025 | 0.63 | $4.70 | $9.31 / 2.05 | 50% | 26% | 21% | 4% | +1.82 | -0.98 |
| 1.0 | 2026 (development) | 0.54 | $8.35 | $16.36 / 1.96 | 54% | 26% | 16% | 4% | +1.91 | -0.99 |
| 1.1 | Training 2023-24 | 0.58 | $1.83 | $3.49 / 1.96 | 57% | 24% | 16% | 3% | +1.61 | -0.95 |
| 1.1 | Validation 2025 | 0.59 | $4.47 | $8.95 / 2.04 | 51% | 25% | 20% | 4% | +1.81 | -0.97 |
| 1.1 | 2026 (development) | 0.55 | $8.65 | $16.49 / 1.92 | 55% | 26% | 16% | 3% | +1.91 | -0.99 |

Mean R by exit reason (all periods, each version):

| Ver | Exit | Trades | Mean R | Sum R |
|---|---|---|---|---|
| 1.0 | stop | 912 | -0.96 | -877.2 |
| 1.0 | target | 433 | +1.73 | 751.2 |
| 1.0 | forced close 16:45 New York | 298 | +0.21 | 61.1 |
| 1.0 | H1 trend invalidated | 55 | -0.54 | -29.5 |
| 1.0 | stop (gap) | 1 | -0.90 | -0.9 |
| 1.1 | stop | 715 | -0.96 | -688.3 |
| 1.1 | target | 324 | +1.74 | 563.9 |
| 1.1 | forced close 16:45 New York | 225 | +0.22 | 50.6 |
| 1.1 | H1 trend invalidated | 43 | -0.54 | -23.3 |
| 1.1 | stop (gap) | 1 | -0.90 | -0.9 |

### Late entries

Two measures of how far into a move the entry is: distance of the entry from H1 EMA50 in H1 ATRs, and the age of the H1 EMA50/EMA200 alignment in H1 bars. Buckets are Version 1.0 Training terciles.

**Distance from H1 EMA50** (cut-offs 1.38, 2.64)

| Ver | Period | Bucket | Trades | Win rate | Mean R [95% CI] | Sum R | PF (R) | Max DD (R) |
|---|---|---|---|---|---|---|---|---|
| 1.0 | Training 2023-24 | near EMA50 | 274 | 35.8% | -0.073 [-0.19, +0.05] | -19.9 | 0.86 | 28.6 |
| 1.0 | Training 2023-24 | middle | 274 | 32.8% | -0.119 [-0.24, +0.01] | -32.5 | 0.79 | 38.5 |
| 1.0 | Training 2023-24 | extended | 275 | 33.1% | -0.154 [-0.28, -0.02] | -42.4 | 0.74 | 47.5 |
| 1.0 | Validation 2025 | near EMA50 | 152 | 40.1% | +0.077 [-0.12, +0.27] | 11.7 | 1.15 | 11.5 |
| 1.0 | Validation 2025 | middle | 134 | 38.8% | -0.030 [-0.23, +0.16] | -4.0 | 0.94 | 18.1 |
| 1.0 | Validation 2025 | extended | 212 | 40.1% | +0.010 [-0.15, +0.17] | 2.0 | 1.02 | 21.4 |
| 1.0 | 2026 (development) | near EMA50 | 132 | 32.6% | -0.054 [-0.26, +0.15] | -7.2 | 0.90 | 14.0 |
| 1.0 | 2026 (development) | middle | 137 | 32.8% | -0.111 [-0.31, +0.11] | -15.1 | 0.82 | 25.9 |
| 1.0 | 2026 (development) | extended | 109 | 41.3% | +0.111 [-0.14, +0.36] | 12.1 | 1.21 | 10.9 |
| 1.1 | Training 2023-24 | near EMA50 | 234 | 34.2% | -0.123 [-0.26, +0.01] | -28.7 | 0.77 | 35.0 |
| 1.1 | Training 2023-24 | middle | 211 | 32.7% | -0.151 [-0.29, -0.00] | -31.9 | 0.74 | 35.3 |
| 1.1 | Training 2023-24 | extended | 191 | 33.0% | -0.186 [-0.34, -0.03] | -35.5 | 0.70 | 39.1 |
| 1.1 | Validation 2025 | near EMA50 | 117 | 41.0% | +0.099 [-0.11, +0.33] | 11.5 | 1.20 | 10.0 |
| 1.1 | Validation 2025 | middle | 95 | 37.9% | -0.048 [-0.27, +0.21] | -4.6 | 0.91 | 15.9 |
| 1.1 | Validation 2025 | extended | 161 | 37.9% | -0.037 [-0.23, +0.16] | -6.0 | 0.94 | 22.7 |
| 1.1 | 2026 (development) | near EMA50 | 98 | 33.7% | +0.003 [-0.24, +0.26] | 0.3 | 1.00 | 13.4 |
| 1.1 | 2026 (development) | middle | 114 | 35.1% | -0.053 [-0.29, +0.19] | -6.1 | 0.91 | 16.3 |
| 1.1 | 2026 (development) | extended | 87 | 37.9% | +0.033 [-0.22, +0.30] | 2.9 | 1.06 | 12.0 |

**H1 trend age** (cut-offs 62.00, 185.00)

| Ver | Period | Bucket | Trades | Win rate | Mean R [95% CI] | Sum R | PF (R) | Max DD (R) |
|---|---|---|---|---|---|---|---|---|
| 1.0 | Training 2023-24 | young | 274 | 34.3% | -0.103 [-0.23, +0.03] | -28.3 | 0.82 | 42.1 |
| 1.0 | Training 2023-24 | middle | 274 | 32.8% | -0.108 [-0.23, +0.01] | -29.6 | 0.80 | 35.7 |
| 1.0 | Training 2023-24 | old | 275 | 34.5% | -0.134 [-0.26, -0.01] | -36.9 | 0.76 | 36.9 |
| 1.0 | Validation 2025 | young | 147 | 36.7% | -0.026 [-0.22, +0.17] | -3.9 | 0.95 | 21.7 |
| 1.0 | Validation 2025 | middle | 133 | 36.1% | -0.103 [-0.28, +0.10] | -13.7 | 0.82 | 19.9 |
| 1.0 | Validation 2025 | old | 218 | 44.0% | +0.125 [-0.03, +0.29] | 27.2 | 1.26 | 7.7 |
| 1.0 | 2026 (development) | young | 156 | 32.1% | -0.073 [-0.26, +0.12] | -11.4 | 0.87 | 26.7 |
| 1.0 | 2026 (development) | middle | 129 | 39.5% | +0.084 [-0.12, +0.31] | 10.9 | 1.16 | 13.2 |
| 1.0 | 2026 (development) | old | 93 | 34.4% | -0.104 [-0.34, +0.15] | -9.7 | 0.83 | 18.1 |
| 1.1 | Training 2023-24 | young | 160 | 33.8% | -0.158 [-0.33, +0.01] | -25.4 | 0.73 | 30.5 |
| 1.1 | Training 2023-24 | middle | 239 | 31.4% | -0.158 [-0.29, -0.03] | -37.8 | 0.72 | 38.2 |
| 1.1 | Training 2023-24 | old | 237 | 35.0% | -0.139 [-0.28, -0.01] | -33.0 | 0.75 | 36.7 |
| 1.1 | Validation 2025 | young | 100 | 33.0% | -0.105 [-0.34, +0.14] | -10.5 | 0.82 | 20.4 |
| 1.1 | Validation 2025 | middle | 90 | 32.2% | -0.155 [-0.39, +0.09] | -14.0 | 0.75 | 19.4 |
| 1.1 | Validation 2025 | old | 183 | 45.4% | +0.139 [-0.03, +0.32] | 25.5 | 1.29 | 7.7 |
| 1.1 | 2026 (development) | young | 108 | 33.3% | -0.006 [-0.23, +0.25] | -0.7 | 0.99 | 16.5 |
| 1.1 | 2026 (development) | middle | 98 | 38.8% | +0.091 [-0.15, +0.35] | 8.9 | 1.17 | 11.6 |
| 1.1 | 2026 (development) | old | 93 | 34.4% | -0.120 [-0.35, +0.14] | -11.2 | 0.80 | 15.8 |

**Entry distance from M15 EMA20** (cut-offs 0.39, 0.81)

| Ver | Period | Bucket | Trades | Win rate | Mean R [95% CI] | Sum R | PF (R) | Max DD (R) |
|---|---|---|---|---|---|---|---|---|
| 1.0 | Training 2023-24 | close to EMA20 | 274 | 33.2% | -0.122 [-0.26, +0.01] | -33.5 | 0.78 | 35.5 |
| 1.0 | Training 2023-24 | middle | 274 | 33.6% | -0.139 [-0.26, -0.01] | -38.0 | 0.75 | 43.0 |
| 1.0 | Training 2023-24 | far from EMA20 | 275 | 34.9% | -0.085 [-0.21, +0.04] | -23.3 | 0.85 | 37.1 |
| 1.0 | Validation 2025 | close to EMA20 | 160 | 38.8% | +0.006 [-0.17, +0.19] | 1.0 | 1.01 | 12.7 |
| 1.0 | Validation 2025 | middle | 147 | 40.1% | +0.067 [-0.12, +0.27] | 9.8 | 1.13 | 13.4 |
| 1.0 | Validation 2025 | far from EMA20 | 191 | 40.3% | -0.006 [-0.17, +0.16] | -1.2 | 0.99 | 22.1 |
| 1.0 | 2026 (development) | close to EMA20 | 157 | 28.7% | -0.155 [-0.34, +0.05] | -24.4 | 0.75 | 30.7 |
| 1.0 | 2026 (development) | middle | 101 | 43.6% | +0.163 [-0.08, +0.42] | 16.5 | 1.32 | 8.6 |
| 1.0 | 2026 (development) | far from EMA20 | 120 | 36.7% | -0.020 [-0.23, +0.20] | -2.4 | 0.97 | 13.6 |
| 1.1 | Training 2023-24 | close to EMA20 | 215 | 33.0% | -0.159 [-0.30, -0.01] | -34.2 | 0.73 | 36.4 |
| 1.1 | Training 2023-24 | middle | 216 | 32.4% | -0.178 [-0.31, -0.04] | -38.4 | 0.69 | 40.5 |
| 1.1 | Training 2023-24 | far from EMA20 | 205 | 34.6% | -0.114 [-0.26, +0.04] | -23.4 | 0.80 | 29.9 |
| 1.1 | Validation 2025 | close to EMA20 | 130 | 40.0% | +0.037 [-0.14, +0.24] | 4.9 | 1.07 | 9.6 |
| 1.1 | Validation 2025 | middle | 106 | 41.5% | +0.116 [-0.11, +0.35] | 12.3 | 1.23 | 9.9 |
| 1.1 | Validation 2025 | far from EMA20 | 137 | 35.8% | -0.118 [-0.29, +0.07] | -16.2 | 0.80 | 26.9 |
| 1.1 | 2026 (development) | close to EMA20 | 122 | 28.7% | -0.152 [-0.37, +0.06] | -18.5 | 0.76 | 28.2 |
| 1.1 | 2026 (development) | middle | 83 | 44.6% | +0.210 [-0.07, +0.48] | 17.5 | 1.43 | 8.9 |
| 1.1 | 2026 (development) | far from EMA20 | 94 | 36.2% | -0.020 [-0.26, +0.23] | -1.9 | 0.96 | 10.5 |

## 5. Transaction costs

| Cost | Status | Source |
|---|---|---|
| Spread | **Measured** (historical bar spread) | one spread value per M15 bar from MT5 history; intrabar widening is not modelled |
| Entry and market-exit slippage | **Assumed scenario**: 7 points in the base | MT5 records no requested price for market orders, so it cannot be measured |
| Stop-loss slippage | **Measured distribution, applied as an assumption**: p90 = 40 points on every stop in the base | 6,583 of the account's own stop exits |
| Take-profit slippage | **Measured**: 0 | 165 take-profit exits, median 0 |
| Commission | **Measured**: £0 | 18,466 historical XAUUSD deals, all 0 |
| Swap | **0 by design** | no overnight positions (forced close 16:45 New York); swap-free account |

| Ver | Period | Gross | Spread | Entry slip | Exit slip | Commission | Swap | Net | Reconciles | Gross R/trade | Cost R/trade | Net R/trade | Gross PF |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1.0 | Training 2023-24 | £-127.22 | £240.52 | £94.37 | £337.69 | £0.00 | £0.00 | £-799.80 | yes | +0.016 | 0.131 | -0.115 | 0.95 |
| 1.0 | Validation 2025 | £523.62 | £153.63 | £70.15 | £228.56 | £0.00 | £0.00 | £71.29 | yes | +0.071 | 0.052 | +0.019 | 1.13 |
| 1.0 | 2026 (development) | £-39.37 | £77.48 | £24.56 | £82.94 | £0.00 | £0.00 | £-224.35 | yes | +0.007 | 0.034 | -0.027 | 0.99 |
| 1.1 | Training 2023-24 | £-139.89 | £238.93 | £92.30 | £332.40 | £0.00 | £0.00 | £-803.53 | yes | -0.023 | 0.128 | -0.151 | 0.94 |
| 1.1 | Validation 2025 | £289.26 | £108.39 | £50.63 | £166.75 | £0.00 | £0.00 | £-36.51 | yes | +0.057 | 0.054 | +0.003 | 1.10 |
| 1.1 | 2026 (development) | £88.38 | £64.49 | £20.50 | £68.06 | £0.00 | £0.00 | £-64.66 | yes | +0.024 | 0.034 | -0.010 | 1.04 |

The cost-scenario grid in each report shows the sensitivity: the optimistic scenario (zero entry slippage, p50 stops) is still negative in Training for both versions.

### Costs by stop distance

Spread and slippage are fixed in points, so they cost more R the tighter the stop. Stop distance in USD per ounce at entry, buckets fixed in advance (not fitted).

| Ver | Stop distance | Trades (all periods) | Gross R/trade | Cost R/trade | Net R/trade | Gross PF (R) | Net PF (R) |
|---|---|---|---|---|---|---|---|
| 1.0 | $0-3 | 351 | +0.022 | 0.183 | -0.161 | 1.05 | 0.73 |
| 1.0 | $3-6 | 508 | +0.058 | 0.100 | -0.041 | 1.12 | 0.93 |
| 1.0 | $6-12 | 375 | +0.005 | 0.051 | -0.046 | 1.01 | 0.91 |
| 1.0 | $12-25 | 437 | +0.032 | 0.028 | +0.004 | 1.06 | 1.01 |
| 1.0 | $25+ | 28 | -0.059 | 0.018 | -0.077 | 0.89 | 0.85 |
| 1.1 | $0-3 | 248 | +0.024 | 0.185 | -0.161 | 1.05 | 0.73 |
| 1.1 | $3-6 | 402 | +0.017 | 0.100 | -0.084 | 1.03 | 0.86 |
| 1.1 | $6-12 | 304 | -0.024 | 0.052 | -0.076 | 0.95 | 0.86 |
| 1.1 | $12-25 | 337 | +0.026 | 0.028 | -0.003 | 1.05 | 1.00 |
| 1.1 | $25+ | 17 | -0.012 | 0.018 | -0.030 | 0.98 | 0.95 |

## 6. Statistical reliability

| Ver | Period | Trades | Mean R [95% CI] | Distinct pullbacks | Sum R | Sum R without best 10 | Losing months | Worst 3 months (R) |
|---|---|---|---|---|---|---|---|---|
| 1.0 | Training 2023-24 | 823 | -0.115 [-0.186, -0.040] | 701 (218 trades share one) | -94.8 | -112.8 | 17 of 24 | 2023-07 -16.0, 2023-02 -16.0, 2023-06 -14.4 |
| 1.0 | Validation 2025 | 498 | +0.019 [-0.084, +0.133] | 421 (139 trades share one) | +9.7 | -9.7 | 6 of 12 | 2025-08 -14.6, 2025-07 -8.1, 2025-01 -4.5 |
| 1.0 | 2026 (development) | 378 | -0.027 [-0.150, +0.106] | 320 (105 trades share one) | -10.2 | -29.7 | 5 of 10 | 2026-07 -14.9, 2026-08 -3.7, 2026-02 -3.6 |
| 1.1 | Training 2023-24 | 636 | -0.151 [-0.235, -0.063] | 538 (173 trades share one) | -96.1 | -114.0 | 18 of 24 | 2023-02 -14.5, 2024-01 -12.9, 2023-07 -11.5 |
| 1.1 | Validation 2025 | 373 | +0.003 [-0.124, +0.121] | 315 (104 trades share one) | +1.0 | -18.3 | 7 of 12 | 2025-08 -13.1, 2025-07 -7.1, 2025-06 -6.1 |
| 1.1 | 2026 (development) | 299 | -0.010 [-0.141, +0.134] | 254 (83 trades share one) | -2.9 | -22.4 | 5 of 10 | 2026-08 -7.5, 2026-07 -5.9, 2026-04 -3.1 |

Version 1.0 trades the Version 1.1 rule would have rejected, and those it keeps (same Version 1.0 trade list, so the comparison is not affected by path changes):

| Period | Group | Trades | Win rate | Mean R [95% CI] | Sum R | PF (R) | Max DD (R) |
|---|---|---|---|---|---|---|---|
| Training 2023-24 | rejected by 1.1 | 247 | 34.8% | -0.064 [-0.20, +0.08] | -15.8 | 0.88 | 30.7 |
| Training 2023-24 | kept by 1.1 | 576 | 33.5% | -0.137 [-0.22, -0.05] | -79.0 | 0.76 | 86.0 |
| Validation 2025 | rejected by 1.1 | 119 | 42.9% | +0.078 [-0.14, +0.30] | 9.2 | 1.16 | 7.6 |
| Validation 2025 | kept by 1.1 | 379 | 38.8% | +0.001 [-0.12, +0.12] | 0.4 | 1.00 | 32.1 |
| 2026 (development) | rejected by 1.1 | 84 | 34.5% | -0.093 [-0.36, +0.18] | -7.8 | 0.84 | 15.5 |
| 2026 (development) | kept by 1.1 | 294 | 35.4% | -0.008 [-0.16, +0.13] | -2.4 | 0.99 | 19.3 |

Risk-rejected signals (minimum volume above 2% of the balance) from the reports:

| Ver | Period | Signal candles | Executable | Rejected: minimum volume | Executed at 0.01 lot | Final balance |
|---|---|---|---|---|---|---|
| 1.0 | Training 2023-24 | 3176 | 823 | 774 | 406 | £200.20 |
| 1.0 | Validation 2025 | 1119 | 498 | 28 | 144 | £1,071.29 |
| 1.0 | 2026 (development) | 1110 | 378 | 165 | 299 | £775.65 |
| 1.1 | Training 2023-24 | 3695 | 636 | 428 | 242 | £196.47 |
| 1.1 | Validation 2025 | 1536 | 373 | 36 | 119 | £963.49 |
| 1.1 | 2026 (development) | 1330 | 299 | 137 | 221 | £935.34 |

