<!-- run 20261111T105736Z_615aacaa1d -->
# EXP-012: quote movement at the modelled entry

Registered before running. Read-only ticks. **Quote movement is not execution slippage:** no order was sent, and real latency is unknown, so the offsets are illustrative.

- Run `20261111T105736Z_615aacaa1d`; code `615aacaa1d5d61c140663efa4776065444017867` on `research/phase2-forward-observation`; working tree clean
- Entries 2025-06-14 to 2026-10-30: 759; observed 759; no quote within 60 s or no bar: none
- Points: 1 point = USD 0.01 per ounce. Adverse = the executable quote (ask for a buy, bid for a sell) moved against the trade, relative to the first quote at or after the entry moment. Quantiles: 10 / 25 / 50 / 75 / 90 / 95%.

## Adverse quote movement after the entry moment (points)

| Group | Entries | +1.0s | +2.0s | +5.0s | +60.0s | Worst within 5 s | Share > 7 pts at +1 s | Share > 40 pts at +1 s |
|---|---|---|---|---|---|---|---|---|
| Strategy A / Asia (19-03 NY) | 7 | -57 / -18 / -2 / -2 / +3 / +3 | -77 / -16 / -1 / +6 / +38 / +38 | -158 / -1 / +10 / +31 / +38 / +38 | -151 / -123 / -70 / +68 / +125 / +125 | +0 / +6 / +17 / +43 / +77 / +77 | 14% | 14% |
| Strategy A / June 2025 (sparse ticks) | 2 | -35 / -35 / -35 / -35 / -35 / -35 | -7 / -7 / -7 / -7 / -7 / -7 | -29 / -29 / -29 / -29 / -29 / -29 | -79 / -79 / -79 / -79 / -79 / -79 | +14 / +14 / +14 / +14 / +14 / +14 | 50% | 0% |
| Strategy A / London (03-08 NY) | 61 | -34 / -7 / +2 / +15 / +37 / +54 | -38 / -9 / +2 / +22 / +53 / +63 | -35 / -21 / +9 / +37 / +70 / +105 | -109 / -64 / +6 / +99 / +172 / +252 | +3 / +10 / +26 / +47 / +81 / +122 | 36% | 8% |
| Strategy A / New York (08-17 NY) | 41 | -47 / -17 / +1 / +42 / +59 / +85 | -71 / -17 / +5 / +31 / +122 / +143 | -129 / -52 / +10 / +45 / +134 / +171 | -346 / -105 / -6 / +105 / +302 / +463 | +2 / +12 / +32 / +95 / +147 / +192 | 39% | 27% |
| Version 1.0 / Asia (19-03 NY) | 321 | -23 / -7 / +1 / +12 / +32 / +47 | -37 / -10 / +3 / +21 / +44 / +63 | -62 / -22 / +2 / +25 / +63 / +86 | -149 / -65 / +5 / +68 / +148 / +208 | +0 / +5 / +19 / +47 / +81 / +121 | 32% | 8% |
| Version 1.0 / June 2025 (sparse ticks) | 17 | -8 / -7 / +0 / +0 / +24 / +25 | -4 / +0 / +7 / +12 / +29 / +32 | -14 / +2 / +8 / +21 / +35 / +43 | -69 / -19 / +15 / +47 / +72 / +144 | +1 / +7 / +15 / +31 / +41 / +48 | 19% | 0% |
| Version 1.0 / London (03-08 NY) | 134 | -19 / -5 / +4 / +16 / +32 / +43 | -25 / -3 / +7 / +20 / +38 / +71 | -43 / -10 / +7 / +28 / +63 / +98 | -154 / -64 / +1 / +57 / +141 / +162 | +2 / +7 / +19 / +41 / +80 / +117 | 41% | 7% |
| Version 1.0 / New York (08-17 NY) | 195 | -32 / -11 / +1 / +18 / +37 / +70 | -46 / -14 / +4 / +23 / +53 / +90 | -56 / -24 / +2 / +28 / +85 / +124 | -181 / -92 / +9 / +89 / +205 / +304 | +0 / +7 / +25 / +47 / +100 / +165 | 38% | 9% |
| all (Strategy A) | 109 | -42 / -12 / +1 / +23 / +50 / +76 | -51 / -13 / +3 / +26 / +63 / +122 | -59 / -27 / +9 / +39 / +80 / +134 | -158 / -76 / -1 / +104 / +216 / +302 | +1 / +10 / +28 / +70 / +117 / +147 | 36% | 16% |
| all (Version 1.0) | 650 | -25 / -8 / +1 / +14 / +34 / +50 | -37 / -10 / +4 / +21 / +46 / +70 | -57 / -21 / +4 / +27 / +65 / +102 | -164 / -75 / +5 / +72 / +155 / +239 | +0 / +6 / +21 / +46 / +87 / +132 | 36% | 8% |

## Backtest entry model against the first real quote (points)

Model = bar open (bid) + bar spread for a buy, bar open for a sell. Positive = the model entry was worse for the trade than the first real quote.

| Group | Model − first quote | First quote spread | First quote delay (s) |
|---|---|---|---|
| Strategy A / Asia (19-03 NY) | -4 / -1 / -1 / -1 / +0 / +0 | +18 / +19 / +23 / +24 / +24 / +24 | 0.0 / 0.0 / 0.0 / 0.0 / 0.1 / 0.1 |
| Strategy A / June 2025 (sparse ticks) | -1 / -1 / -1 / -1 / -1 / -1 | +18 / +18 / +18 / +18 / +18 / +18 | 0.0 / 0.0 / 0.0 / 0.0 / 0.0 / 0.0 |
| Strategy A / London (03-08 NY) | -1 / +0 / +0 / +0 / +0 / +0 | +18 / +19 / +21 / +23 / +24 / +24 | 0.0 / 0.0 / 0.0 / 0.1 / 0.1 / 0.2 |
| Strategy A / New York (08-17 NY) | -1 / -1 / +0 / +0 / +0 / +0 | +18 / +19 / +20 / +23 / +24 / +25 | 0.0 / 0.0 / 0.0 / 0.1 / 0.1 / 0.1 |
| Version 1.0 / Asia (19-03 NY) | -1 / -1 / +0 / +0 / +0 / +0 | +18 / +19 / +21 / +23 / +24 / +26 | 0.0 / 0.0 / 0.0 / 0.1 / 0.1 / 0.2 |
| Version 1.0 / June 2025 (sparse ticks) | -11 / +0 / +0 / +2 / +5 / +13 | +17 / +17 / +17 / +19 / +19 / +19 | 0.0 / 0.1 / 0.3 / 0.4 / 0.5 / 0.6 |
| Version 1.0 / London (03-08 NY) | -1 / -1 / +0 / +0 / +0 / +0 | +18 / +19 / +21 / +23 / +24 / +25 | 0.0 / 0.0 / 0.0 / 0.1 / 0.1 / 0.2 |
| Version 1.0 / New York (08-17 NY) | -1 / -1 / +0 / +0 / +0 / +0 | +18 / +19 / +21 / +23 / +24 / +26 | 0.0 / 0.0 / 0.0 / 0.1 / 0.1 / 0.1 |
| all (Strategy A) | -1 / -1 / +0 / +0 / +0 / +0 | +18 / +19 / +21 / +23 / +24 / +25 | 0.0 / 0.0 / 0.0 / 0.1 / 0.1 / 0.1 |
| all (Version 1.0) | -1 / -1 / +0 / +0 / +0 / +0 | +18 / +19 / +21 / +23 / +24 / +26 | 0.0 / 0.0 / 0.0 / 0.1 / 0.1 / 0.2 |

## How to read this

- **Assumed entry slippage:** the base scenario assumes 7 points; the scenarios also use 0 and 40.
- **Comparing:** the rows show how often the quote itself moved more than that within 1 second of the modelled entry. This bounds part of the uncertainty. Real slippage also depends on order latency and broker execution, which only a separately authorised demo execution study could measure.
- **No decision:** this changes no frozen experiment (EXP-011). Any new cost assumption would need a new registered experiment.
