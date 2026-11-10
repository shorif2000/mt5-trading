from trading.risk.risk_engine import RiskPolicy, validate_policy


def test_unconfigured_policy_fails_closed():
    policy = RiskPolicy(
        enabled=False,
        account_currency=None,
        maximum_risk_per_trade_percent=None,
        maximum_daily_loss_percent=None,
        maximum_open_positions=None,
        maximum_total_open_risk_percent=None,
        minimum_reward_to_risk=None,
        allow_trading=False,
    )
    result = validate_policy(policy)
    assert not result.accepted
    assert result.reasons


def test_policy_cannot_enable_execution_in_this_version():
    policy = RiskPolicy(
        enabled=True,
        account_currency="GBP",
        maximum_risk_per_trade_percent=0.1,
        maximum_daily_loss_percent=1.0,
        maximum_open_positions=1,
        maximum_total_open_risk_percent=0.2,
        minimum_reward_to_risk=1.5,
        allow_trading=True,
    )
    result = validate_policy(policy)
    assert not result.accepted
