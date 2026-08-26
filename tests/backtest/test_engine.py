import numpy as np
import pandas as pd
import pytest

from quant.backtest.engine import Backtester
from quant.data.synthetic_provider import SyntheticDataProvider
from quant.strategy.base import BaseStrategy
from quant.strategy.mean_reversion import RSIReversalStrategy
from quant.strategy.trend_following import DualMovingAverageStrategy


class _AlwaysFullyLongStrategy(BaseStrategy):
    id = "always_long"
    family = "test"

    def generate_weights(self, ohlcv_map, feature_map=None, benchmark_close=None):
        signals = {}
        for sym, df in ohlcv_map.items():
            signals[sym] = pd.Series(1.0, index=df.index)
        return self._combine_signals(signals)


class _FlatStrategy(BaseStrategy):
    id = "always_flat"
    family = "test"

    def generate_weights(self, ohlcv_map, feature_map=None, benchmark_close=None):
        signals = {}
        for sym, df in ohlcv_map.items():
            signals[sym] = pd.Series(0.0, index=df.index)
        return self._combine_signals(signals)


@pytest.fixture(scope="module")
def provider():
    return SyntheticDataProvider(market="korea", n_symbols=8, n_etfs=0,
                                  start="2018-01-01", end="2022-12-31", seed=13)


@pytest.fixture(scope="module")
def ohlcv_map(provider):
    symbols = [s.symbol for s in provider.list_symbols()]
    return {s: provider.get_ohlcv(s, "2018-01-01", "2022-12-31") for s in symbols}


def test_flat_strategy_preserves_capital_exactly(ohlcv_map):
    bt = Backtester("korea", initial_capital=10_000_000)
    result = bt.run(_FlatStrategy(), ohlcv_map)
    assert not result.equity_curve.empty
    assert result.equity_curve.iloc[-1] == pytest.approx(10_000_000, rel=1e-9)
    assert result.total_cost == 0.0


def test_always_long_single_symbol_tracks_price_after_costs():
    provider = SyntheticDataProvider(market="korea", n_symbols=1, n_etfs=0,
                                      start="2018-01-01", end="2020-12-31", seed=1)
    sym = provider.list_symbols()[0].symbol
    ohlcv = {sym: provider.get_ohlcv(sym, "2018-01-01", "2020-12-31")}

    bt = Backtester("korea", initial_capital=10_000_000)
    result = bt.run(_AlwaysFullyLongStrategy(), ohlcv, symbol_meta={sym: {"asset_type": "equity", "exchange": "KOSPI"}})

    price_return = ohlcv[sym]["adj_close"].iloc[-1] / ohlcv[sym]["adj_close"].iloc[0] - 1
    nav_return = result.equity_curve.iloc[-1] / result.initial_capital - 1
    # NAV return should track the underlying price return closely (small
    # negative drag from the one-time entry cost + 1-day fill delay), not be
    # wildly different in sign or magnitude
    assert abs(nav_return - price_return) < 0.05
    assert result.total_cost > 0  # entering the position was not free


def test_trades_recorded_on_signal_changes():
    provider = SyntheticDataProvider(market="korea", n_symbols=4, n_etfs=0,
                                      start="2018-01-01", end="2020-12-31", seed=2)
    symbols = [s.symbol for s in provider.list_symbols()]
    ohlcv = {s: provider.get_ohlcv(s, "2018-01-01", "2020-12-31") for s in symbols}

    bt = Backtester("korea")
    strategy = RSIReversalStrategy(rsi_window=14, oversold=30, overbought=70)
    result = bt.run(strategy, ohlcv)
    assert len(result.trades) > 0
    assert all(t.cost >= 0 for t in result.trades)
    assert all(t.side in ("buy", "sell") for t in result.trades)


def test_volume_cap_limits_trade_size():
    idx = pd.bdate_range("2020-01-01", periods=50)
    close = pd.Series(np.linspace(100, 110, 50), index=idx)
    # extremely thin volume: 10 shares/day at price ~100 = ~1000 notional/day
    df = pd.DataFrame({
        "open": close, "high": close * 1.001, "low": close * 0.999, "close": close,
        "volume": 10, "adj_close": close,
    }, index=idx)
    ohlcv = {"THIN": df}

    bt = Backtester("korea", initial_capital=100_000_000)  # capital >> tradable liquidity
    result = bt.run(_AlwaysFullyLongStrategy(), ohlcv, symbol_meta={"THIN": {"asset_type": "equity", "exchange": "KOSPI"}})

    max_single_day_notional = (10 * close * 0.05).max()  # max_participation_of_volume default 0.05
    trade_notionals = [t.notional for t in result.trades]
    assert max(trade_notionals) <= max_single_day_notional * 1.01


def test_no_lookahead_equity_curve_is_causal():
    provider = SyntheticDataProvider(market="korea", n_symbols=5, n_etfs=0,
                                      start="2017-01-01", end="2022-12-31", seed=4)
    symbols = [s.symbol for s in provider.list_symbols()]
    full_ohlcv = {s: provider.get_ohlcv(s, "2017-01-01", "2022-12-31") for s in symbols}

    cutoff = "2020-06-01"
    truncated_ohlcv = {s: df.loc[:cutoff] for s, df in full_ohlcv.items()}

    strategy_full = DualMovingAverageStrategy(fast_window=10, slow_window=30)
    strategy_trunc = DualMovingAverageStrategy(fast_window=10, slow_window=30)

    bt = Backtester("korea")
    result_full = bt.run(strategy_full, full_ohlcv)
    result_trunc = bt.run(strategy_trunc, truncated_ohlcv)

    common_idx = result_trunc.equity_curve.index
    pd.testing.assert_series_equal(
        result_full.equity_curve.loc[common_idx], result_trunc.equity_curve, check_names=False, rtol=1e-6,
    )


def test_empty_weights_returns_empty_result():
    bt = Backtester("korea")

    class _NoOpStrategy(BaseStrategy):
        def generate_weights(self, ohlcv_map, feature_map=None, benchmark_close=None):
            return pd.DataFrame()

    result = bt.run(_NoOpStrategy(), {})
    assert result.equity_curve.empty
    assert result.trades == []
