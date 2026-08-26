import pandas as pd
import pytest

from quant.data.synthetic_provider import SyntheticDataProvider
from quant.features import fundamental as fnd
from quant.features.engine import FeatureEngine
from quant.strategy import registry


@pytest.fixture(scope="module")
def provider():
    return SyntheticDataProvider(market="korea", n_symbols=20, n_etfs=0,
                                  start="2015-01-01", end="2023-12-31", seed=17)


@pytest.fixture(scope="module")
def context(provider):
    symbols = [s.symbol for s in provider.list_symbols()]
    ohlcv_map = {s: provider.get_ohlcv(s, "2015-01-01", "2023-12-31") for s in symbols}
    index_ohlcv = provider.get_index_ohlcv("KOSPI", "2015-01-01", "2023-12-31")

    engine = FeatureEngine("korea")
    feature_map = engine.compute_panel(ohlcv_map, benchmark_close=index_ohlcv["close"])
    rank_wide = engine.cross_sectional_momentum_rank(feature_map)
    feature_map = engine.attach_momentum_rank(feature_map, rank_wide)

    all_dates = index_ohlcv.index
    rebalance_dates = pd.date_range("2016-01-01", "2023-12-31", freq="MS")
    fund_series = fnd.build_fundamental_score_series(provider, symbols, all_dates, rebalance_dates)
    feature_map = engine.attach_fundamental_scores(feature_map, fund_series)

    return ohlcv_map, feature_map, index_ohlcv["close"]


@pytest.mark.parametrize("strategy_id", registry.enabled_strategy_ids())
def test_every_enabled_strategy_produces_valid_weights(strategy_id, context):
    ohlcv_map, feature_map, benchmark_close = context
    strategy = registry.build_strategy(strategy_id)
    weights = strategy.generate_weights(ohlcv_map, feature_map=feature_map, benchmark_close=benchmark_close)

    assert isinstance(weights, pd.DataFrame)
    if weights.empty:
        pytest.skip(f"{strategy_id} produced no weights with this fixture (likely missing optional data)")

    assert (weights.fillna(0) >= -1e-9).all().all()
    assert (weights.fillna(0) <= 1 + 1e-9).all().all()

    # Only cross-sectional strategies (momentum/factor/multi_factor families)
    # are required to already sum to <= 1 per date -- time-series strategies
    # (trend_following/momentum-absolute/mean_reversion/volatility) legally
    # emit independent 0/1 per symbol and can have several "on"
    # simultaneously; the backtester's row-normalization step (not the
    # strategy) is what turns that into portfolio weights. See
    # strategy/base.py's module docstring for the full weight contract.
    if strategy.family in ("factor", "multi_factor") or strategy_id in ("cs_momentum", "relative_strength"):
        row_sums = weights.fillna(0).sum(axis=1)
        assert (row_sums <= 1 + 1e-6).all()


def test_registry_rejects_unknown_id():
    with pytest.raises(KeyError):
        registry.build_strategy("not_a_real_strategy")


def test_build_all_enabled_returns_all_configured_strategies():
    strategies = registry.build_all_enabled()
    assert set(strategies.keys()) == set(registry.enabled_strategy_ids())
    assert len(strategies) >= 10
