# Experiment registry

Every experiment is recorded here **before** any result is computed. Use one file per
experiment, named `EXP-NNN-<slug>.md`. Never edit a registered entry after its first run.
Changes go in a new experiment, which links back to the original.

| Id | Title | Status | Registered | Specification | Result |
|---|---|---|---|---|---|
| EXP-001 | Break-even exits on Version 1.0 entries | run | 2026-11-11 | `EXP-001-breakeven-exits.md` | run: `../../../reports/research/EXP-001_f1c41d8ec1.md` |
| EXP-002 | Strategy A event study (2023–2024) | run | 2026-11-11 | `EXP-002-strategy-a-event-study.md` | run: `../../../reports/research/EXP-002_c860443017.md` |
| EXP-003 | Strategy A backtest (cost-floor arms) | run | 2026-11-11 | `EXP-003-strategy-a-backtest.md` | run: `../../../reports/research/EXP-003_c860443017.md` |
| EXP-004 | Strategy C event study (2023–2024) | run | 2026-11-11 | `EXP-004-strategy-c-event-study.md` | run: `../../../reports/research/EXP-004_9294d7b6de.md` |
| EXP-005 | Strategy C backtest (cost-floor arms) | run | 2026-11-11 | `EXP-005-strategy-c-backtest.md` | run: `../../../reports/research/EXP-005_9294d7b6de.md` |
| EXP-006 | Strategy B event study (2023–2024) | run | 2026-11-11 | `EXP-006-strategy-b-event-study.md` | run: `../../../reports/research/EXP-006_806154fa75.md` |
| EXP-007 | Strategy B backtest (cost-floor arms) | run | 2026-11-11 | `EXP-007-strategy-b-backtest.md` | run: `../../../reports/research/EXP-007_806154fa75.md` |
| EXP-008 | Strategy A backtest, complete news calendar (rerun of EXP-003) | run | 2026-11-11 | `EXP-008-strategy-a-backtest-full-calendar.md` | run: `../../../reports/research/EXP-008_ec87e37dc2.md` |
| EXP-009 | Strategy C backtest, complete news calendar (rerun of EXP-005) | run | 2026-11-11 | `EXP-009-strategy-c-backtest-full-calendar.md` | run: `../../../reports/research/EXP-009_c73e00cac4.md` |
| EXP-010 | Strategy B backtest, complete news calendar (rerun of EXP-007) | run | 2026-11-11 | `EXP-010-strategy-b-backtest-full-calendar.md` | run: `../../../reports/research/EXP-010_6d09960f77.md` |

## Template

```markdown
# EXP-NNN: <title>

- Status: draft | approved | registered | run | superseded by EXP-MMM
- Registered: <date, commit> (before any result)
- Hypothesis: <one falsifiable sentence>
- Strategy or specification: <document and version>
- Data: <files with sha256, periods, which periods are development, validation or hold-out>
- Rules: <exact, machine-testable, every parameter value>
- Costs: <measured inputs, assumed scenarios>
- Ledgers: fixed risk (2% of £1,000) and compounding (2% of balance)
- Event definition: <what counts as one independent setup event>
- Metrics: <list>
- Decision rule: <pre-declared; what result would reject or carry the hypothesis forward>
- Known limitations: <intrabar modelling, data gaps, news>
- Comparisons so far in the programme: <count>
- Result: <link to report, added after the run>
```
| EXP-011 | Strategy A forward test (frozen; from 2026-11-16) | registered, collecting | 2026-11-11 | `EXP-011-strategy-a-forward-test.md` | weekly reports in `../../../reports/forward/` |
| EXP-012 | Quote movement at the modelled entry (historical ticks) | run | 2026-11-11 | `EXP-012-quote-movement-at-entry.md` | run: `../../../reports/research/EXP-012_615aacaa1d.md` |
