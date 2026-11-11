"""Shared inputs for research backtests, loaded exactly as the Version 1.0 `backtest` command
loads them (same files, same parsing), so research runs use identical terms and costs."""

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from trading.backtest.bars import Bar
from trading.backtest.cost_model import CostModel, load_cost_model
from trading.backtest.engine import BacktestConfig
from trading.backtest.history_bars import load_history
from trading.market_data.mcp_export import ExportSettings, load_mcp_export
from trading.market_data.sessions import MarketCalendar, load_market_calendar
from trading.models import InstrumentSpec
from trading.risk.sizing_config import load_sizing_config

HISTORY = Path("data/history/xauusd_backtest.local.json")
EXPORT = Path("data/mcp_export.local.json")
SESSIONS = Path("config/market_sessions.yaml")
RISK = Path("config/risk.yaml")
COSTS = Path("config/backtest.yaml")


@dataclass(frozen=True)
class ResearchInputs:
    m15: list[Bar]
    h1: list[Bar]
    gbpusd_m15: list[Bar]
    spec: InstrumentSpec
    conversion_spec: InstrumentSpec
    calendar: MarketCalendar
    cost_model: CostModel
    base_config: BacktestConfig
    paths: dict[str, Path]


def load_inputs(
    history: Path = HISTORY,
    export: Path = EXPORT,
    sessions: Path = SESSIONS,
    risk: Path = RISK,
    costs: Path = COSTS,
) -> ResearchInputs:
    calendar = load_market_calendar(sessions)
    raw = json.loads(export.read_text(encoding="utf-8"))
    snapshot = load_mcp_export(
        export,
        now=datetime.fromisoformat(raw["exported_at_utc"]),
        settings=ExportSettings(
            calendar=calendar,
            max_export_age_seconds=10**9,
            max_quote_age_seconds=10**9,
            min_completed_candles=1,
        ),
    )
    spec = next(i for i in snapshot.instruments if i.symbol == "XAUUSD")
    conversion_spec = next(i for i in snapshot.instruments if i.symbol == "GBPUSD")
    account = snapshot.account
    if account.stop_out_mode is None or account.margin_call_level is None:
        raise ValueError("export lacks the account margin-call settings")
    model = load_cost_model(costs)
    base_config = BacktestConfig(
        starting_balance=model.starting_balance,
        account_currency=account.currency,
        stop_out_mode=account.stop_out_mode,
        margin_call_level=Decimal(str(account.margin_call_level)),
        sizing=load_sizing_config(risk),
        costs=model.base(),
    )
    bars = load_history(history)
    return ResearchInputs(
        m15=bars[("XAUUSD", "M15")],
        h1=bars[("XAUUSD", "H1")],
        gbpusd_m15=bars[("GBPUSD", "M15")],
        spec=spec,
        conversion_spec=conversion_spec,
        calendar=calendar,
        cost_model=model,
        base_config=base_config,
        paths={"history": history, "specification_export": export, "sessions": sessions,
               "risk_config": risk, "cost_config": costs},
    )  # fmt: skip
