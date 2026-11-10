# MT5 integration assessment

Assessed 2026-11-10 against `~/meta-trader-5-mcp` at commit `b280d4d` and the live terminal,
using read-only tools only. Source paths below are relative to that repository unless they
start with `src/trading` or `tests/`.

## 1. Bridge architecture

```
Claude Code ──stdio MCP──> mt5-mcp (macOS, Python 3.13)          src/mt5_mcp/
                              │ NDJSON over TCP 127.0.0.1:18812, shared token
                           mt5-bridge (inside Wine, Python 3.12)  bridge/src/mt5_bridge/
                              │ official MetaTrader5 package
                           terminal64.exe (logged-in account)
```

Registered in `~/.claude.json` (user scope) as:
`uv --directory /Users/Mohammed/meta-trader-5-mcp run mt5-mcp`, with no `env` entries, so
`MT5_ENABLE_TRADING` defaults to `0` (`src/mt5_mcp/config.py`).

## 2. Tools

Read tools are registered in `src/mt5_mcp/tools_read.py`, all annotated `read_only_hint=True`.
Trading tools (`place_order`, `modify_position_sltp`, `modify_pending_order`, `close_position`,
`cancel_order`) are registered only when `MT5_ENABLE_TRADING=1` (`src/mt5_mcp/server.py:47`).
The bridge also refuses `order_send` unless launched with trading enabled
(`bridge/src/mt5_bridge/methods.py`, `requires_trading=True`).

| Tool | Inputs | Output (key fields) | Used by this app |
|---|---|---|---|
| `terminal_status` | none | `mcp_trading_enabled`, `bridge_reachable`, `bridge.trading_allowed_by_bridge`, `terminal.{connected, trade_allowed}`, `broker_offset_seconds`, `broker_offset_confident` | yes |
| `get_account_info` | none | MT5 `account_info()`: `login`, `trade_mode` (0 demo, 1 contest, 2 real), `balance`, `credit`, `equity`, `margin`, `margin_free`, `margin_level`, `currency`, `server` | yes |
| `list_symbols` | `group`, `limit` | name, path, currencies, digits, visible, trade_mode | symbol verification only |
| `get_symbol_info` | `symbol` | MT5 `symbol_info()`: `point`, `digits`, `trade_contract_size`, `trade_tick_size`, `trade_tick_value`, `volume_min/max/step`, `trade_mode`, currencies | yes |
| `get_tick` | `symbol` | `time`, `time_msc`, `bid`, `ask`, `time_utc`, `time_broker` + offset info | yes |
| `get_rates` | `symbol`, `timeframe`, `count` / `start` / `end` | `rates[]` of `time`, `open`, `high`, `low`, `close`, `tick_volume`, `spread`, `real_volume`, `time_utc`; `truncated` | yes |
| `get_positions` | `symbol` or `ticket` | `count`, `positions[]` with `ticket`, `type` (0 BUY, 1 SELL), `volume`, `price_open`, `sl`, `tp`, `profit`, `time` | yes |
| `get_orders` | `symbol` or `ticket` | `count`, `orders[]` with `ticket`, `type` (2–7 pending kinds), `volume_current`, `price_open`, `price_stoplimit`, `sl`, `tp`, `time_setup`, `time_expiration` | yes |
| `get_ticks`, `get_history_orders`, `get_history_deals` | ranges | history | no |
| `calc_margin`, `calc_profit` | symbol, side, volume, prices | broker calculations | no (future risk work) |
| `check_order` | full order request | MT5 `order_check` dry run, nothing sent | **never used** |

Output schemas are the MT5 package's named tuples converted to dicts
(`bridge/src/mt5_bridge/convert.py`) and decorated by `src/mt5_mcp/shaping.py`.
MT5 uses `0` for unset SL, TP, stop-limit price and expiration.

Strictly read-only notes:
- `get_symbol_info`, `get_tick`, `get_rates` call `symbol_select` when MT5 refuses an unknown
  symbol (`src/mt5_mcp/service.py:12`). This can add a symbol to Market Watch: a terminal
  display change, not an account or trading change.
- `check_order` is annotated read-only and sends nothing, but it builds a full order request.
  This app excludes it from its allowlist.

## 3. Time representation

`src/mt5_mcp/timeconv.py`. MT5 returns broker server time as a "fake UTC" epoch. Real UTC is
`epoch - offset`. The offset is estimated from the freshest tick and rounded to 15 minutes
(`src/mt5_mcp/context.py:81`). It is accepted only within 90 s of a quarter hour. Otherwise a
cached value is used with `broker_offset_confident: false`, or `null` when none was ever
known. `*_utc` fields are omitted when the offset is unknown. `*_broker` strings have **no zone
marker**. `MT5_BROKER_UTC_OFFSET_HOURS` can fix the offset.

Observed live: offset `7200` (UTC+2), confident. Before the terminal connected, the offset was
`null` and every `*_utc` field was missing.

## 4. Errors, timeouts and limitations

- Connect timeout 3 s and read timeout 30 s (`src/mt5_mcp/bridge_client.py:20`). The bridge
  readiness wait is 90 s (`config.py:40`). The bridge is auto-started on first call and
  restarted once for read methods (`context.py:61`).
- Errors become MCP tool errors with readable text (`src/mt5_mcp/errors.py`): bridge
  unavailable, auth, not connected, MT5 error code.
- `terminal_status` returns `bridge_reachable: false` with an `error` instead of raising.
- Bars and ticks are capped by `MT5_MAX_BARS` (5000). Range queries keep the earliest bars and
  set `truncated`.
- Count-mode `get_rates` includes the **currently forming bar** as its last row.
- **Observed: a disconnected terminal still answers.** It returned cached account data and bar
  history that was months old. After it connected, the reported positions and pending orders
  differed from the cached ones.
- **Observed: right after reconnecting**, GBPUSD and USDJPY returned history ending in
  2024 until MT5 had synced. A retry a few seconds later was complete.
- The bridge allows 16 concurrent connections (`bridge/src/mt5_bridge/server.py:41`). A second
  `mt5-mcp` process reuses a running bridge (`src/mt5_mcp/launcher.py`, `ensure_bridge`).
- HTTP mode (`src/mt5_mcp/http.py`) serves only price tools, not account, positions or orders.

Verified broker symbols: `EURUSD`, `GBPUSD`, `USDJPY` (3 digits), `XAUUSD` (2 digits,
contract size 100). `XAUUSD.crp` exists but is a conversion-only symbol (`trade_mode` 0) and
must not be used. Check `account_info.trade_mode` before every session: the terminal may be
logged into a live account.

## 5. Integration approach

**A. Claude exports a JSON snapshot.** Claude calls the MCP tools and writes the results to a
file for Python. *Rejected as the main path after a trial.* A useful export holds about 1,400
bars. Writing it out by hand takes minutes, so it can never meet the 120 s freshness limit.
Transcription is also a fidelity risk for prices, and the project rules forbid inventing them.

**B. Python uses a documented read-only interface of the existing bridge.** Options considered:

| Option | Verdict |
|---|---|
| Raw bridge TCP socket | Rejected. It needs the shared bridge token, and the same socket serves `order_send`. |
| `mt5-mcp --http` | Rejected. It needs an API key and a running server, and it does not serve account, positions or orders. |
| **Python MCP client to `mt5-mcp` over stdio** | **Chosen.** |

**Chosen:** a Python MCP stdio client (`src/trading/market_data/mcp_collector.py`). It starts
the same registered server command with `MT5_ENABLE_TRADING=0` forced and talks MCP, a
documented protocol. It reuses the running bridge and the terminal's existing connection, so no
second MT5 connection or bridge is created. It does **not** call Claude's MCP session.

Safety in the collector:
- The server command is not a user option. It is read from the user-scope `mt5` entry in
  `~/.claude.json` and must be exactly `<absolute path to uv> --directory <existing absolute
  repo> run mt5-mcp` over stdio, with no `MT5_ENABLE_TRADING` other than `0`. It is started
  as an argument list, never through a shell, with a minimal environment and
  `MT5_ENABLE_TRADING=0` forced.
- It refuses to run if the server advertises any tool without `read_only_hint=True`. That
  includes a missing annotation, `false`, or a tool also marked `destructive_hint=True`.
  Every trading tool is covered (`tools_trade.py` annotates them `read_only_hint=False`).
- Only 7 allowlisted tools are ever called. `check_order` and `calc_*` are excluded.
- `login`, `name`, `server` and `company` are replaced with `REDACTED` before the raw export
  is written.

Two stages keep acquisition and validation separate:

```
mt5-trading collect  ->  data/mcp_export.local.json   (raw MCP tool responses, git-ignored)
mt5-trading ingest   ->  data/snapshot.local.json     (validated MarketSnapshot, git-ignored)
mt5-trading diagnose --snapshot data/snapshot.local.json
```

The raw export format (`mt5-mcp-export/v1`) is plain tool output, so Claude can still produce
one by hand for a small manual check. Python validates it the same way.

## 6. Validation rules (`src/trading/market_data/mcp_export.py`)

Rejects the whole export, listing every reason, when any of these holds:

- **Trading not confirmed off:** `mcp_trading_enabled`, bridge trading or MT5 Algo Trading is
  not explicitly `false`.
- **Connection:**
  - the bridge is unreachable,
  - the terminal is not connected to the broker, or
  - any tool call failed or timed out (recorded as `tool_error`).
- **Time:**
  - the broker offset is unknown or not confident,
  - it is not a 15-minute multiple,
  - a response reports a different offset,
  - a bridge `*_utc` value disagrees with our conversion,
  - `exported_at_utc` is timezone-naive, or
  - a tick is in the future.
- **Freshness:**
  - the export is older than 120 s,
  - a tick is older than 120 s, or
  - the latest completed candle is more than one bar old.
- **Candles:**
  - missing or truncated response,
  - fewer than 50 completed bars,
  - not strictly ascending,
  - not aligned to the timeframe,
  - invalid OHLC,
  - more than one incomplete bar, or
  - a gap longer than 75 min that is not the weekend close.
- **The currently forming candle is always dropped.** A bar counts as complete only when
  `open + duration <= exported_at_utc`, and `exported_at_utc` is taken *before* any data is
  read. `CandleSeries` enforces this again at model level.
- **Specs:**
  - name differs from the requested symbol (catches `XAUUSD.crp`),
  - non-positive contract size, tick size, tick value or volumes, or
  - `volume_max < volume_min`.

  `trade_allowed` is true only for full trade mode (4).
- **Positions and orders:**
  - `count` mismatch,
  - unknown position type, or
  - a non-pending order type in the pending list.

  MT5's `0` for SL, TP, stop-limit and expiration becomes `null`.

Every timestamp is kept twice. `timestamp` is aware UTC. `broker_time` is the same instant in
the broker's fixed offset, for example `2026-11-10T21:00:00+02:00`. Models reject a
`broker_time` that is not the same instant. The account login is replaced with `REDACTED`.

## 7. Example export (synthetic)

`data/example_mcp_export.json` is **entirely synthetic**: the account, balances, leverage, server,
instrument specifications, prices, positions, orders and timestamps are fictional. It has 3 bars
per timeframe, so it passes validation only with `min_completed_candles=2`, which a test checks.
Excerpt (the last M15 row is the forming bar, which `ingest` drops):

```json
{
  "format": "mt5-mcp-export/v1",
  "exported_at_utc": "2030-01-08T10:00:30+00:00",
  "terminal_status": {
    "mcp_trading_enabled": false,
    "bridge": {
      "trading_allowed_by_bridge": false
    },
    "terminal": {
      "connected": true,
      "trade_allowed": false
    },
    "broker_offset_seconds": 7200,
    "broker_offset_confident": true
  },
  "account_info": {
    "login": "REDACTED",
    "server": "REDACTED",
    "trade_mode": 0,
    "currency": "USD",
    "balance": 10000.0
  },
  "symbols": {
    "EURUSD": {
      "tick": {
        "time": 1894104029,
        "bid": 1.1,
        "ask": 1.1001,
        "time_utc": "2030-01-08T10:00:29Z",
        "time_broker": "2030-01-08T12:00:29"
      },
      "rates": {
        "M15": {
          "truncated": false,
          "rates": [
            {
              "time": 1894104000,
              "open": 1.1,
              "high": 1.1002,
              "low": 1.0998,
              "close": 1.1001,
              "tick_volume": 100,
              "spread": 10,
              "real_volume": 0,
              "time_utc": "2030-01-08T10:00:00Z"
            }
          ]
        }
      }
    }
  }
}
```

## 8. Running diagnostics

```bash
uv run mt5-trading collect            # read-only tools only; trading forced off
uv run mt5-trading ingest --export data/mcp_export.local.json
uv run mt5-trading diagnose --snapshot data/snapshot.local.json
```

`ingest` exits with code 2 and lists every reason when data is rejected. `diagnose` exits with
code 3 when the snapshot is older than `--maximum-age-seconds`. If collection fails, run the
`terminal_status` MCP tool in Claude, or read `~/Library/Logs/mt5-mcp/bridge.log`.

## 9. Outstanding limitations

- Gap detection is a heuristic. It tolerates breaks of 75 minutes or less and the Friday to
  Sunday close. Holidays and broker maintenance will cause rejections; rerun later or review
  them manually.
- The weekend rule uses UTC weekdays. It has not been validated against this broker's DST
  transitions.
- MT5 account info has no broker timestamp. `AccountSnapshot.timestamp` is the local
  collection start time (`exported_at_utc`), recorded before `get_account_info` is called. It
  is not a broker-generated time and does not prove the account figures are fresh.
- `tick_value` is MT5's current value, which changes with conversion rates. It must be
  refreshed for every sizing calculation. `trade_tick_value_loss` (which can differ) is not yet
  captured.
- `calculation_currency` (margin currency) is left unset pending a decision on its meaning.
- Correlated exposure and currency conversion are not computed.
- The terminal may be logged into a live account. Read-only access is enforced by this app, by the
  `mt5-mcp` configuration and by the bridge. It still relies on the registered server keeping
  `MT5_ENABLE_TRADING` unset.
- No economic calendar source is integrated.
