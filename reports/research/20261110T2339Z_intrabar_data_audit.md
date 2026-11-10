# XAUUSD M1 and tick history audit (read-only)

- **Run:** 2026-11-10 23:39 UTC, `uv run python scripts/mt5_intrabar_audit.py`.
- **Access:** read-only MT5 MCP. The session refused to start unless every advertised tool was
  annotated read-only. Only `terminal_status`, `get_ticks` and `get_rates` were called.
- **Terminal state at the run:** connected; build 6230; `trade_allowed: false`;
  `mcp_trading_enabled: false`. No orders, positions or settings were touched.

## Bridge diagnosis

- **What failed:** earlier in the session the bridge reported `WinError 10048` (address in
  use) on port 18812.
- **Why:** `lsof` shows the port held by `wineserver`, the process running the **existing**
  bridge. The failed starts were duplicate launches made while the first bridge was still
  serving. Its log shows it kept answering connections, and `terminal_status` succeeded.
- **Action:** none needed. No process was killed or restarted.

## Findings

| Data | Result |
|---|---|
| Earliest tick | broker time 2025-06-13 09:18:13, i.e. **2025-06-13 06:18:13 UTC**. The server labels it 07:18 because it converts with today's offset; see the caveat below. The same tick comes back for any earlier start (2015, 2024, 2025-06-02). |
| Tick fields | bid and ask on every tick sampled. `last` and `volume` are 0 (spot quotes, no traded volume). |
| Tick coverage | 1,116 samples (three times each weekday, 2025-06-09 to 2026-11-10): **1,094 found a tick within 2 minutes**. The 22 misses are: before the first tick (9–13 Jun 2025), 25 Dec 2025, 1 Jan 2026, and 3 Apr 2026 (Good Friday). |
| Tick density | about 12–14 ticks per second at 14:30 UTC: 5,000 ticks in 7–10 minutes. Zero empty bids or asks. Median spread 19–22 points. |
| M1 bars | **100,002 bars, 2026-07-31 05:49 UTC to 2026-11-10 23:39 UTC**. This is a rolling window: the start moved from 06:16 to 06:49 (server labels) between two probes about 33 minutes apart, consistent with a terminal cap of about 100,000 bars. One gap over 15 minutes in scheduled hours: 2026-09-07 18:30–22:00 UTC (US Labor Day early close). |
| M15 and H1 (existing file) | 2022-10-30 to 2026-10-30, unchanged. |

**Caveat on times:** the MCP server converts request times and `*_utc` labels with the broker
offset in force now (UTC+2). Broker time is New York + 7 hours, so it is UTC+3 during US
daylight saving, and summer timestamps are labelled one hour late. Research code must convert
raw broker times with the project's DST-aware `BrokerClock`, never use the `*_utc` labels.

## Is it enough for intrabar break-even research?

| Period | Tick coverage | M1 coverage | Intrabar resolution possible? |
|---|---|---|---|
| Training 2023–2024 | none | none | **No.** M15 bar-close rule only; ambiguous bars bounded. |
| Validation 2025 | from 13 Jun (about 55% of the year) | none | **Partly**, for trades from 13 Jun 2025 |
| 2026 development | full except holidays | from 31 Jul (rolling) | **Yes**, from ticks |

- **Conclusion:** the M15 bar-close rule stays the primary method for all periods. Ticks can
  settle ambiguous trigger bars only from 13 June 2025.
- **Use in EXP-001:** a separate sensitivity analysis, not a change to the primary results.
- **M1 is not useful:** it adds nothing beyond the ticks, and its start keeps moving forward.
- **Coverage is sampled, not exhaustive:** three samples a day can miss short outages, so each
  tick-resolved bar is checked for ticks covering the whole bar.
