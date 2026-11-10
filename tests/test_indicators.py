import pytest

from trading.analysis.indicators import atr, sma


def test_sma_calculates_last_period():
    assert sma([1, 2, 3, 4], 3) == 3


def test_sma_rejects_insufficient_data():
    with pytest.raises(ValueError):
        sma([1, 2], 3)


def test_atr_uses_true_range():
    assert atr([10, 12], [8, 9], [9, 11], 2) == 2.5
