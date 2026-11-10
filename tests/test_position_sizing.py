from decimal import Decimal as D

from trading.risk.position_sizing import calculate_volume


def test_position_size_rounds_down_to_volume_step():
    result = calculate_volume(
        risk_cash=D("10"),
        entry=D("1.1000"),
        stop=D("1.0950"),
        tick_size=D("0.0001"),
        tick_value_per_lot=D("10"),
        volume_min=D("0.01"),
        volume_max=D("10"),
        volume_step=D("0.01"),
        direction="buy",
    )
    assert result.accepted
    assert result.volume == D("0.02")
    assert result.estimated_loss <= D("10")


def test_rejects_when_minimum_volume_exceeds_risk():
    result = calculate_volume(
        risk_cash=D("1"),
        entry=D("1.1000"),
        stop=D("1.0950"),
        tick_size=D("0.0001"),
        tick_value_per_lot=D("10"),
        volume_min=D("0.01"),
        volume_max=D("10"),
        volume_step=D("0.01"),
        direction="buy",
    )
    assert not result.accepted
    assert result.volume is None


def test_rejects_wrong_side_stop():
    result = calculate_volume(
        risk_cash=D("10"),
        entry=D("1.1000"),
        stop=D("1.1010"),
        tick_size=D("0.0001"),
        tick_value_per_lot=D("10"),
        volume_min=D("0.01"),
        volume_max=D("10"),
        volume_step=D("0.01"),
        direction="buy",
    )
    assert not result.accepted
