import pandas as pd
import pytest

from quant.analytics.benchmark import buy_and_hold_equity_curve, compare_to_benchmark
from quant.backtest.engine import Backtester
from quant.data.synthetic_provider import SyntheticDataProvider
from quant.strategy.trend_following import DualMovingAverageStrategy


@pytest.fixture(scope="module")
def provider():
    return SyntheticDataProvider(market="korea", n_symbols=10, n_etfs=0,
                                  start="2016-01-01", end="2022-12-31", seed=31)


def test_buy_and_hold_starts_at_initial_capital(provider):
    idx_df = provider.get_index_ohlcv("KOSPI", "2016-01-01", "2022-12-31")
    equity = buy_and_hold_equity_curve(idx_df, initial_capital=1_000_000)
    assert equity.iloc[0] == pytest.approx(1_000_000)


def test_compare_to_benchmark_reports_excess_return(provider):
    symbols = [s.symbol for s in provider.list_symbols()]
    ohlcv_map = {s: provider.get_ohlcv(s, "2016-01-01", "2022-12-31") for s in symbols}
    idx_df = provider.get_index_ohlcv("KOSPI", "2016-01-01", "2022-12-31")

    bt = Backtester("korea")
    result = bt.run(DualMovingAverageStrategy(20, 60), ohlcv_map)

    comparison = compare_to_benchmark(result.equity_curve, result.daily_returns, idx_df, bt.initial_capital)
    assert "excess_total_return" in comparison
    assert comparison["strategy_metrics"].total_return is not None
    assert comparison["benchmark_metrics"].total_return is not None
    assert not comparison["benchmark_equity"].empty
