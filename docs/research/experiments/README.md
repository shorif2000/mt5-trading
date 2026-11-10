# Experiment registry

Every experiment is recorded here **before** any result is computed. Use one file per
experiment, named `EXP-NNN-<slug>.md`. Never edit a registered entry after its first run.
Changes go in a new experiment, which links back to the original.

| Id | Title | Status | Registered | Specification |
|---|---|---|---|---|
| EXP-001 | Break-even exits on Version 1.0 entries | draft, awaiting approval | n/a | `../xauusd-research-programme.md`, section 3 |

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
