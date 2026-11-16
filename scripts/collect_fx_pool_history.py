"""Read-only history collection for the FX pool (EURUSD, USDJPY) and the GBPJPY conversion
leg USDJPY needs (GBPUSD M15 is already collected in data/history/xauusd_backtest.local.json
and is reused for EURUSD and GBPUSD itself). Same date bounds as the existing XAUUSD history,
so all four instruments' Training/Validation/2026 periods line up exactly.

    uv run python scripts/collect_fx_pool_history.py

Downloads only (get_rates, read-only); no orders, no account access.
"""

from datetime import UTC, datetime
from pathlib import Path

from trading.market_data.history import download_history_to_file

OUTPUT = Path("data/history/fx_pool.local.json")
START = datetime(2022, 11, 1, tzinfo=UTC)
END = datetime(2026, 11, 1, tzinfo=UTC)
# H1 is collected for consistency with the existing pipeline; Strategy A does not use it
# (confirmed: GenericStrategyA.scan() and CandidateBacktest.run() never read self.h1).
# GBPUSD M15 is already collected in data/history/xauusd_backtest.local.json; only its H1 is
# missing from that file and is added here for the same completeness reason.
REQUESTS = [("EURUSD", "H1"), ("EURUSD", "M15"), ("USDJPY", "H1"), ("USDJPY", "M15"),
            ("GBPJPY", "H1"), ("GBPJPY", "M15"), ("GBPUSD", "H1")]  # fmt: skip


def main() -> None:
    result = download_history_to_file(OUTPUT, requests=REQUESTS, start=START, end=END)
    for series in result["series"]:
        print(f"{series['symbol']} {series['timeframe']}: {len(series['rates'])} bars, "
              f"{len(series['problems'])} problems")  # fmt: skip
    print(f"History written to {OUTPUT}")


if __name__ == "__main__":
    main()
