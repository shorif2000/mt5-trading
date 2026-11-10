"""Position sizing configuration from ``config/risk.yaml``.

Values the broker does not publish through MT5 (commission, slippage) must be set explicitly
per symbol. ``null`` means "not yet known": sizing for that symbol is then rejected rather
than assumed to be zero.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

# The approved ceiling. Configuration may lower it but never raise it, and nothing adjusts it
# at runtime (no increases after losses or with strategy confidence).
MAXIMUM_RISK_PER_TRADE_PERCENT = Decimal("2")


@dataclass(frozen=True)
class SizingConfig:
    risk_fraction: Decimal  # 0.02 for 2 % of the current balance
    maximum_data_age_seconds: int
    tick_value_tolerance: Decimal  # allowed relative difference, e.g. 0.02
    commission_currency: str | None
    # Round-turn commission per lot in ``commission_currency``; None = not known.
    commission_per_lot: Mapping[str, Decimal | None]
    # Total adverse slippage allowance in points (entry and stop together); None = not known.
    slippage_points: Mapping[str, Decimal | None]


def _decimal(value: object, where: str, *, allow_none: bool = False) -> Decimal | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise ValueError(f"{where}: must be a number")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{where}: must be a number") from exc
    if not number.is_finite():
        raise ValueError(f"{where}: must be finite")
    return number


def _required_decimal(value: object, where: str) -> Decimal:
    number = _decimal(value, where)
    if number is None:
        raise ValueError(f"{where}: required")
    return number


def _per_symbol(value: object, where: str) -> dict[str, Decimal | None]:
    if not isinstance(value, dict):
        raise ValueError(f"{where}: must map symbols to values")
    result = {}
    for symbol, raw in value.items():
        number = _decimal(raw, f"{where}.{symbol}", allow_none=True)
        if number is not None and number < 0:
            raise ValueError(f"{where}.{symbol}: must not be negative")
        result[str(symbol)] = number
    return result


def parse_sizing_config(data: object) -> SizingConfig:
    if not isinstance(data, dict):
        raise ValueError("risk config: must be a mapping")
    percent = _required_decimal(
        data.get("maximum_risk_per_trade_percent"), "maximum_risk_per_trade_percent"
    )
    if percent <= 0 or percent > MAXIMUM_RISK_PER_TRADE_PERCENT:
        raise ValueError(
            f"maximum_risk_per_trade_percent: must be above 0 and at most "
            f"{MAXIMUM_RISK_PER_TRADE_PERCENT}"
        )
    section: Mapping[str, Any] = data.get("position_sizing") or {}
    if not isinstance(section, dict):
        raise ValueError("position_sizing: must be a mapping")
    age = section.get("maximum_data_age_seconds")
    if isinstance(age, bool) or not isinstance(age, int) or age <= 0:
        raise ValueError("position_sizing.maximum_data_age_seconds: must be a positive integer")
    tolerance = _required_decimal(
        section.get("tick_value_tolerance_percent"), "position_sizing.tick_value_tolerance_percent"
    )
    if tolerance <= 0 or tolerance > 10:
        raise ValueError("position_sizing.tick_value_tolerance_percent: must be in (0, 10]")
    currency = section.get("commission_currency")
    if currency is not None and (not isinstance(currency, str) or not currency):
        raise ValueError("position_sizing.commission_currency: must be a currency code or null")
    return SizingConfig(
        risk_fraction=percent / 100,
        maximum_data_age_seconds=age,
        tick_value_tolerance=tolerance / 100,
        commission_currency=currency,
        commission_per_lot=_per_symbol(
            section.get("commission_per_lot_round_turn"),
            "position_sizing.commission_per_lot_round_turn",
        ),
        slippage_points=_per_symbol(
            section.get("slippage_points"), "position_sizing.slippage_points"
        ),
    )


def load_sizing_config(path: Path) -> SizingConfig:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read risk config {path}: {exc}") from exc
    return parse_sizing_config(data)
