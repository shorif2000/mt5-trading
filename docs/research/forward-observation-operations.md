# Strategy A forward observation: operations

How to run the frozen forward test (EXP-011, `strategy-a-forward-test.md`). Everything here
is read-only. **No orders are placed.**

## Collect (at least daily, ideally every 15 minutes)

```bash
cd ~/mt5-trading && uv run python scripts/forward_observe.py
```

- **Needs:** the MT5 terminal and bridge running (the read-only `mt5` MCP server).
- **Refuses to run** if any frozen file has changed (`docs/research/strategy-a-freeze.json`).
- **Safe to repeat:** signals and quote observations are only appended, never duplicated. A
  missed run is caught up by the next one, as long as the broker still has the ticks.
- **Example cron entry** (you add it yourself with `crontab -e`; nothing is installed for you):
  ```
  */15 * * * 0-5 cd ~/mt5-trading && /usr/bin/env uv run python scripts/forward_observe.py >> data/forward/observer.local.log 2>&1
  ```

## Report (weekly)

```bash
uv run python scripts/strategy_a_monitor.py
```

- **Output:** a new report in `reports/forward/`. Earlier reports are never replaced.
- **Before evaluation:** each arm stays "NOT READY" until it has 100 events and 26 weeks of
  data. Until then, results are descriptive only.
- **Contents:** evidence only. The report never makes a buy or sell recommendation.

## Keep the calendar current (about monthly)

```bash
bash scripts/save_bls_pages.sh        # save the 4 BLS pages in Chrome
bash scripts/download_bls_releases.sh # identified request; asks for your contact email
uv run python scripts/build_economic_calendar.py
```

- **FOMC times:** new FOMC statement times need their release pages added to
  `data/calendar/raw/fomc/` and the Fed calendar page refreshed. Until then, an FOMC meeting
  without a published time blocks its whole New York day.

## Commit weekly

```bash
git add data/forward/strategy_a_signals.jsonl data/forward/strategy_a_quotes.jsonl reports/forward
git commit -m "Strategy A forward observation: week ending YYYY-MM-DD"
```

The bar store (`data/forward/bars.local.json`) stays git-ignored. The signal and quote logs
contain market data only.
