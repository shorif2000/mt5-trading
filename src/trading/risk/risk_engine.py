"""Fail-closed proposal risk checks."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskDecision:
    accepted: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RiskPolicy:
    enabled: bool
    account_currency: str | None
    maximum_risk_per_trade_percent: float | None
    maximum_daily_loss_percent: float | None
    maximum_open_positions: int | None
    maximum_total_open_risk_percent: float | None
    minimum_reward_to_risk: float | None
    allow_trading: bool


def validate_policy(policy: RiskPolicy) -> RiskDecision:
    missing: list[str] = []
    required = {
        "account_currency": policy.account_currency,
        "maximum_risk_per_trade_percent": policy.maximum_risk_per_trade_percent,
        "maximum_daily_loss_percent": policy.maximum_daily_loss_percent,
        "maximum_open_positions": policy.maximum_open_positions,
        "maximum_total_open_risk_percent": policy.maximum_total_open_risk_percent,
        "minimum_reward_to_risk": policy.minimum_reward_to_risk,
    }
    missing.extend(name for name, value in required.items() if value is None)
    if not policy.enabled:
        missing.append("risk policy is disabled")
    if policy.allow_trading:
        missing.append("this application version does not permit trading")
    if missing:
        return RiskDecision(False, tuple(f"Unconfigured or prohibited: {item}" for item in missing))
    return RiskDecision(False, ("No execution capability exists in this version.",))
