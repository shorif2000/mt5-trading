"""Forward-observation plumbing for the FX pool (EXP-014: EURUSD, GBPUSD, USDJPY), run
alongside EXP-011's own XAUUSD stream. A separate module from the frozen `forward.py` (which
is itself frozen for EXP-011) so that this pool's freeze never depends on editing it; the
readiness/evaluation logic (`readiness`, `evaluate`, `MIN_EVENTS`, `MIN_WEEKS`, `CI_LEVEL`) is
imported from it unchanged and reused, since none of that is symbol-specific.

Forward start is the same moment as EXP-011's (2026-11-15 23:00 UTC, trading day
2026-11-16): the three instruments pool with the XAUUSD stream from the same clock, for the
combined readiness threshold (programme Amendment 6).
"""

import hashlib
import json
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from trading.backtest.bars import Bar
from trading.backtest.cost_model import load_cost_model
from trading.backtest.engine import BacktestConfig
from trading.backtest.history_bars import load_history
from trading.market_data.sessions import load_market_calendar
from trading.models import InstrumentSpec
from trading.research.forward import FORWARD_START, forward_signals
from trading.research.multi_market import GenericStrategyA
from trading.risk.sizing_config import SizingConfig

FREEZE_RECORD = Path("docs/research/strategy-a-fx-pool-freeze.json")
INSTRUMENTS: tuple[tuple[str, str], ...] = (
    ("EURUSD", "GBPUSD"),
    ("GBPUSD", "GBPUSD"),  # self-converting: GBP per USD from the GBPUSD bar itself
    ("USDJPY", "GBPJPY"),
)
# Everything that decides a signal, its filters, sizing or costs for the FX pool, on top of
# what EXP-011's own freeze already covers (programme Amendment 6; the "forex" session
# profile in config/market_sessions.yaml and the shared files below are depended on by both
# pools, so either freeze catches a change to them independently).
FROZEN_FILES: tuple[str, ...] = (
    "docs/research/strategy-a-fx-pool.md",
    "src/trading/research/multi_market.py",
    "src/trading/research/fx_pool_forward.py",
    "docs/research/xauusd-strategy-candidates.md",
    "src/trading/research/candidates.py",
    "src/trading/research/levels.py",
    "src/trading/research/candidate_engine.py",
    "src/trading/research/news.py",
    "src/trading/research/stats.py",
    "src/trading/backtest/engine.py",
    "src/trading/strategies/xauusd_m15_pullback.py",
    "src/trading/analysis/indicators.py",
    "src/trading/risk/position_sizing.py",
    "src/trading/risk/margin.py",
    "src/trading/risk/sizing_config.py",
    "config/backtest.yaml",
    "config/market_sessions.yaml",
)
M15 = timedelta(minutes=15)


def digest(paths: Iterable[str] = FROZEN_FILES) -> dict[str, str]:
    return {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths}


def freeze_mismatches(record: Path = FREEZE_RECORD) -> list[str]:
    frozen = json.loads(record.read_text(encoding="utf-8"))["files"]
    current = digest(frozen)
    return sorted(p for p, sha in frozen.items() if current[p] != sha)


def completed(bars: Sequence[Bar], now: datetime, step: timedelta = M15) -> list[Bar]:
    return [b for b in bars if b.open_time + step <= now]


def merge_rows(stored: Iterable[dict[str, Any]], fresh: Iterable[dict[str, Any]]
               ) -> list[dict[str, Any]]:  # fmt: skip
    rows = {r["time"]: r for r in stored}
    rows.update({r["time"]: r for r in fresh})
    return [rows[t] for t in sorted(rows)]


def forward_signals_for(
    symbol: str, strategy: GenericStrategyA, start: datetime = FORWARD_START
) -> list[dict[str, Any]]:
    """`trading.research.forward.forward_signals`, which only reads `.m15`/`.signals` (never a
    hardcoded symbol), with the instrument tagged onto each record."""
    return [{"symbol": symbol, **row} for row in forward_signals(strategy, start)]


# --- shared inputs (specs verified read-only 2026-11-16: list_symbols, get_symbol_info) ----


def _spec(symbol: str, base: str, quote: str, tick: float, digits: int) -> InstrumentSpec:
    return InstrumentSpec(
        symbol=symbol, base_currency=base, quote_currency=quote, contract_size=100000,
        tick_size=tick, tick_value=0.8, tick_value_loss=0.8, tick_value_profit=0.8,
        volume_min=0.01, volume_max=100, volume_step=0.01, trade_allowed=True, digits=digits,
        point=tick, stops_level_points=0,
    )  # fmt: skip


SPECS = {
    "EURUSD": _spec("EURUSD", "EUR", "USD", 0.00001, 5),
    "GBPUSD": _spec("GBPUSD", "GBP", "USD", 0.00001, 5),
    "USDJPY": _spec("USDJPY", "USD", "JPY", 0.001, 3),
    "GBPJPY": _spec("GBPJPY", "GBP", "JPY", 0.001, 3),
}
# Commission verified from this account's own deal history (get_history_deals, 2026-11-16):
# 43 EURUSD, 42 GBPUSD, 10 USDJPY deals, every one at 0 commission.
COMMISSION_PER_LOT = {"EURUSD": Decimal(0), "GBPUSD": Decimal(0), "USDJPY": Decimal(0)}


class FxPoolInputs:
    def __init__(self) -> None:
        self.bars = load_history(Path("data/history/fx_pool.local.json"))
        # GBPUSD M15 (and, unused by Strategy A, its H1) is already collected alongside
        # XAUUSD's own history; GBPUSD is reused from there rather than downloaded twice.
        xauusd_history = load_history(Path("data/history/xauusd_backtest.local.json"))
        self.bars[("GBPUSD", "M15")] = xauusd_history[("GBPUSD", "M15")]
        self.calendar = load_market_calendar(Path("config/market_sessions.yaml"))
        self.cost_model = load_cost_model(Path("config/backtest.yaml"))
        self.sizing = SizingConfig(
            risk_fraction=Decimal("0.02"), maximum_data_age_seconds=10**9,
            tick_value_tolerance=Decimal("0.02"), commission_currency="GBP",
            commission_per_lot=COMMISSION_PER_LOT,
            slippage_points=dict.fromkeys(COMMISSION_PER_LOT, None),
        )  # fmt: skip
        self.base_config = BacktestConfig(
            starting_balance=self.cost_model.starting_balance, account_currency="GBP",
            stop_out_mode=0, margin_call_level=Decimal("50"), sizing=self.sizing,
            costs=self.cost_model.base(),
        )  # fmt: skip

    def m15(self, symbol: str) -> list[Bar]:
        return self.bars[(symbol, "M15")]

    def h1(self, symbol: str) -> list[Bar]:
        return self.bars[(symbol, "H1")]
