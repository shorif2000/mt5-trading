"""Backtest cost model: evidenced stop slippage and labelled entry scenarios."""

from decimal import Decimal as D
from pathlib import Path

import pytest
import yaml

from trading.backtest.cost_model import load_cost_model, parse_cost_model, stop_slippage_points


def deal(side: str, price: float, order: int, reason: int = 4) -> dict[str, object]:
    return {"symbol": "XAUUSD", "type_name": side, "price": price, "order": order, "reason": reason}


def test_stop_slippage_is_measured_adversely_for_both_sides():
    orders = [{"ticket": t, "symbol": "XAUUSD", "price_open": 2000.0} for t in (1, 2, 3, 4)]
    deals = [
        deal("SELL", 1999.90, 1),  # long stopped out 10 points worse
        deal("BUY", 2000.25, 2),  # short stopped out 25 points worse
        deal("SELL", 2000.03, 3),  # long stopped out 3 points better
        deal("SELL", 1990.00, 4, reason=5),  # a take profit: excluded
        deal("SELL", 1990.00, 99),  # no matching order: excluded
    ]
    assert stop_slippage_points(deals, orders) == [-3.0, 10.0, 25.0]


def repo_config() -> dict[str, object]:
    return yaml.safe_load(Path("config/backtest.yaml").read_text())


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda c: c.update(sizing_stop_percentile="p999"), "sizing_stop_percentile"),
        (lambda c: c["stop_loss_slippage_points"].update(p95=5), "must not decrease"),
        (lambda c: c["base_scenario"].update(entry="guess"), "base_scenario"),
        (lambda c: c["entry_slippage_scenarios_points"].update(zero=-1), "must not be negative"),
    ],
)
def test_invalid_cost_configuration_is_rejected(change, message):
    config = repo_config()
    change(config)
    with pytest.raises(ValueError, match=message):
        parse_cost_model(config)


def test_every_scenario_sizes_for_at_least_what_it_simulates():
    model = load_cost_model(Path("config/backtest.yaml"))
    p95 = model.stop_percentiles["p95"]
    for costs in model.grid():
        assert "SCENARIO" in costs.label  # entry slippage is never presented as a fact
        assert costs.sizing_allowance() >= costs.entry_points + max(costs.stop_exit_points, p95)
        assert costs.market_exit_points == costs.entry_points
    assert model.base().stop_exit_points == D("40") and model.base().entry_points == D("7")
