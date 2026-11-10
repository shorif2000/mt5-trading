from trading.reporting.performance import summarise_results


def test_performance_summary():
    result = summarise_results([10, -5, 15, -5])
    assert result.trade_count == 4
    assert result.net_profit == 15
    assert result.win_rate == 0.5
    assert result.profit_factor == 2.5
