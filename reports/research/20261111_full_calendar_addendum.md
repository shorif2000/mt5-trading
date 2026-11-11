# Complete news calendar: reruns alongside the original FOMC-only results

The **original runs (EXP-003, EXP-005, EXP-007) are unchanged**; they remain the record with the FOMC-only filter. EXP-008, EXP-009 and EXP-010 were registered before running (programme Amendment 4) and differ only in the news filter: FOMC statements, CPI and Employment Situation, with every release time verified (`config/economic_calendar.yaml`, commit `0c489c1`). Base scenario, fixed-risk ledger. Generated from the run manifests.

| Strategy | Arm | Run | News filter | Trades (T / V / 2026) | Net R/trade (T / V / 2026) | Pooled net R [95% CI] | Signals excluded by calendar | Classification |
|---|---|---|---|---|---|---|---|---|
| A | 0.10R cost floor | EXP-003 | FOMC only | 38 / 42 / 49 | -0.092 / +0.032 / -0.005 | -0.018 [-0.230, +0.205] | 0 | ASSUMPTION-DEPENDENT (positive only with zero entry slippage); INSUFFICIENT DATA in Validation 2025, 2026 (development) |
| A | no cost floor | EXP-003 | FOMC only | 200 / 67 / 55 | -0.119 / -0.062 / +0.040 | -0.080 [-0.208, +0.059] | 0 | INCONCLUSIVE; INSUFFICIENT DATA in Validation 2025, 2026 (development) |
| A | 0.10R cost floor | EXP-008 | FOMC + CPI + payrolls | 38 / 42 / 49 | -0.092 / +0.032 / -0.005 | -0.018 [-0.230, +0.205] | 1 | ASSUMPTION-DEPENDENT (positive only with zero entry slippage); INSUFFICIENT DATA in Validation 2025, 2026 (development) |
| A | no cost floor | EXP-008 | FOMC + CPI + payrolls | 199 / 67 / 55 | -0.115 / -0.062 / +0.040 | -0.077 [-0.207, +0.056] | 1 | INCONCLUSIVE; INSUFFICIENT DATA in Validation 2025, 2026 (development) |
| C | 0.10R cost floor | EXP-005 | FOMC only | 63 / 70 / 53 | -0.012 / +0.011 / -0.332 | -0.094 [-0.259, +0.076] | 0 | INCONCLUSIVE; INSUFFICIENT DATA in 2026 (development) |
| C | no cost floor | EXP-005 | FOMC only | 198 / 91 / 54 | -0.155 / -0.076 / -0.293 | -0.156 [-0.277, -0.031] | 0 | NEGATIVE; INSUFFICIENT DATA in 2026 (development) |
| C | 0.10R cost floor | EXP-009 | FOMC + CPI + payrolls | 63 / 70 / 53 | -0.012 / +0.011 / -0.332 | -0.094 [-0.259, +0.076] | 0 | INCONCLUSIVE; INSUFFICIENT DATA in 2026 (development) |
| C | no cost floor | EXP-009 | FOMC + CPI + payrolls | 198 / 91 / 54 | -0.155 / -0.076 / -0.293 | -0.156 [-0.277, -0.031] | 0 | NEGATIVE; INSUFFICIENT DATA in 2026 (development) |
| B | 0.10R cost floor | EXP-007 | FOMC only | 0 / 0 / 0 | n/a / n/a / n/a | n/a | 0 | INCONCLUSIVE; INSUFFICIENT DATA in Training 2023-24, Validation 2025, 2026 (development) |
| B | no cost floor | EXP-007 | FOMC only | 1 / 0 / 0 | +1.418 / n/a / n/a | +1.418 [+1.418, +1.418] | 0 | INCONCLUSIVE; INSUFFICIENT DATA in Training 2023-24, Validation 2025, 2026 (development) |
| B | 0.10R cost floor | EXP-010 | FOMC + CPI + payrolls | 0 / 0 / 0 | n/a / n/a / n/a | n/a | 0 | INCONCLUSIVE; INSUFFICIENT DATA in Training 2023-24, Validation 2025, 2026 (development) |
| B | no cost floor | EXP-010 | FOMC + CPI + payrolls | 1 / 0 / 0 | +1.418 / n/a / n/a | +1.418 [+1.418, +1.418] | 0 | INCONCLUSIVE; INSUFFICIENT DATA in Training 2023-24, Validation 2025, 2026 (development) |

## What changed

- **One signal** is excluded in total: a single strategy A signal in Training 2023–24, in both arms.
  - **No cost floor:** one trade fewer; Training net R moves from −0.119 to −0.115 per trade.
  - **0.10R cost floor:** that signal would have failed the cost floor anyway (news is checked first), so the trades are unchanged.
- C and B: no signal excluded.
- **Every pre-registered classification is unchanged.**
- **Why the effect is so small:** CPI and payroll releases are at 08:30 New York, so they block entries only from 08:00 to 08:45 on about 24 days a year, and few signals land in that window.
- **The earlier conclusions stand:**
  - no break-even variant or strategy is adopted;
  - C without the floor is negative;
  - A and C with the floor are inconclusive;
  - B can't be evaluated.

## Calendar provenance

- **FOMC:** each statement time from its federalreserve.gov release page.
- **CPI and Employment Situation:**
  - publication dates from the BLS archive pages (saved by the owner in a browser);
  - times from each release's own embargo statement. The 96 releases were downloaded with a request identifying the tool and a contact, as BLS asks scripts to do.
- **2025:** October 2025 CPI and Employment Situation were not published (BLS: lapse in appropriations).
- **Stored in git:** the official index pages, plus `data/calendar/bls_release_evidence.tsv` (URL, sha256 and embargo sentence for each release). The calendar rebuilds identically from these.

