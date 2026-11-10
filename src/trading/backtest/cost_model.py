"""Backtest execution cost model: evidenced stop-loss slippage and labelled entry scenarios."""

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from trading.backtest.engine import ExecutionCosts

STOP_LOSS_REASON = 4  # MT5 DEAL_REASON_SL


@dataclass(frozen=True)
class CostModel:
    starting_balance: Decimal
    stop_percentiles: dict[str, Decimal]
    sizing_stop_percentile: str
    take_profit_points: Decimal
    entry_scenarios: dict[str, Decimal]
    base_entry: str
    base_stop_percentile: str

    def scenario(self, entry: str, stop_percentile: str) -> ExecutionCosts:
        entry_points = self.entry_scenarios[entry]
        stop_points = self.stop_percentiles[stop_percentile]
        sizing_stop = max(stop_points, self.stop_percentiles[self.sizing_stop_percentile])
        return ExecutionCosts(
            entry_points=entry_points,
            stop_exit_points=stop_points,
            market_exit_points=entry_points,
            take_profit_points=self.take_profit_points,
            sizing_stop_points=sizing_stop,
            label=(
                f"entry {entry} ({entry_points} pts, SCENARIO) / stop exits {stop_percentile} "
                f"({stop_points} pts, evidence) / sizing allowance "
                f"{entry_points + sizing_stop} pts"
            ),
        )

    def base(self) -> ExecutionCosts:
        return self.scenario(self.base_entry, self.base_stop_percentile)

    def grid(self) -> list[ExecutionCosts]:
        return [
            self.scenario(e, p)
            for e in self.entry_scenarios
            for p in ("p50", "p90", "p95")
            if p in self.stop_percentiles
        ]


def _points(value: object, where: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{where}: must be a number of points")
    try:
        points = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{where}: must be a number of points") from exc
    if points < 0:
        raise ValueError(f"{where}: must not be negative")
    return points


def parse_cost_model(data: Any) -> CostModel:
    if not isinstance(data, dict):
        raise ValueError("backtest config: must be a mapping")
    stops = data.get("stop_loss_slippage_points")
    entries = data.get("entry_slippage_scenarios_points")
    base = data.get("base_scenario")
    if not isinstance(stops, dict) or not stops:
        raise ValueError("stop_loss_slippage_points: required percentiles")
    if not isinstance(entries, dict) or not entries:
        raise ValueError("entry_slippage_scenarios_points: required scenarios")
    if not isinstance(base, dict):
        raise ValueError("base_scenario: required")
    model = CostModel(
        starting_balance=_points(data.get("starting_balance_gbp"), "starting_balance_gbp"),
        stop_percentiles={
            k: _points(v, f"stop_loss_slippage_points.{k}") for k, v in stops.items()
        },
        sizing_stop_percentile=str(data.get("sizing_stop_percentile")),
        take_profit_points=_points(
            data.get("take_profit_slippage_points"), "take_profit_slippage_points"
        ),
        entry_scenarios={
            k: _points(v, f"entry_slippage_scenarios_points.{k}") for k, v in entries.items()
        },
        base_entry=str(base.get("entry")),
        base_stop_percentile=str(base.get("stop_percentile")),
    )
    if model.sizing_stop_percentile not in model.stop_percentiles:
        raise ValueError("sizing_stop_percentile: must be one of the stop percentiles")
    if (
        model.base_entry not in model.entry_scenarios
        or model.base_stop_percentile not in model.stop_percentiles
    ):
        raise ValueError("base_scenario: must name a configured entry scenario and stop percentile")
    values = list(model.stop_percentiles.values())
    if values != sorted(values):
        raise ValueError("stop_loss_slippage_points: percentiles must not decrease")
    return model


def load_cost_model(path: Path) -> CostModel:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read backtest config {path}: {exc}") from exc
    return parse_cost_model(data)


def stop_slippage_points(
    deals: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    symbol: str = "XAUUSD",
    point: float = 0.01,
) -> list[float]:
    """Adverse slippage of stop-loss exits: deal price against the stop order's price."""
    by_ticket = {o.get("ticket"): o for o in orders if o.get("symbol") == symbol}
    values = []
    for deal in deals:
        if deal.get("symbol") != symbol or deal.get("reason") != STOP_LOSS_REASON:
            continue
        side = deal.get("type_name")
        order = by_ticket.get(deal.get("order"))
        if side not in ("BUY", "SELL") or not order or not order.get("price_open"):
            continue
        difference = (deal["price"] - order["price_open"]) / point
        values.append(round(difference if side == "BUY" else -difference, 1))
    return sorted(values)


def summarise(values: list[float]) -> dict[str, float]:
    if not values:
        raise ValueError("no stop-loss exits with a stop price were found")
    n = len(values)

    def q(p: float) -> float:
        return values[min(n - 1, int(p * n))]

    return {
        "count": n,
        "p50": q(0.5),
        "p75": q(0.75),
        "p90": q(0.9),
        "p95": q(0.95),
        "p99": q(0.99),
        "max": values[-1],
        "mean": round(sum(values) / n, 1),
        "favourable_share": round(sum(v < 0 for v in values) / n, 3),
    }


def evidence_from_history(path: Path) -> dict[str, float]:
    history = json.loads(path.read_text(encoding="utf-8"))["account_history"]
    return summarise(stop_slippage_points(history["deals"], history["orders"]))
