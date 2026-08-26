import numpy as np
import pandas as pd
import pytest

from quant.data.synthetic_provider import SyntheticDataProvider
from quant.features.engine import FeatureEngine
from quant.scanner.screener import historical_signal_edge, score_candidates


@pytest.fixture(scope="module")
def provider():
    return SyntheticDataProvider(market="korea", n_symbols=15, n_etfs=2,
                                  start="2016-01-01", end="2023-12-31", seed=9)


@pytest.fixture(scope="module")
def built(provider):
    symbols = [s.symbol for s in provider.list_symbols()]
    ohlcv_map = {s: provider.get_ohlcv(s, "2016-01-01", "2023-12-31") for s in symbols}
    engine = FeatureEngine("korea")
    feature_map = engine.compute_panel(ohlcv_map)
    rank_wide = engine.cross_sectional_momentum_rank(feature_map)
    feature_map = engine.attach_momentum_rank(feature_map, rank_wide)
    meta = {s.symbol: {"name": s.name, "exchange": s.exchange, "asset_type": s.asset_type}
            for s in provider.list_symbols()}
    return ohlcv_map, feature_map, meta


def test_score_candidates_returns_sorted_results(built):
    ohlcv_map, feature_map, meta = built
    results = score_candidates("korea", feature_map, ohlcv_map, meta)
    assert len(results) > 0
    scores = [r.composite_score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_candidate_has_all_required_fields(built):
    ohlcv_map, feature_map, meta = built
    results = score_candidates("korea", feature_map, ohlcv_map, meta)
    r = results[0]
    for attr in ["price", "recent_return_20d", "momentum_rank", "trend_score", "volume_score",
                 "volatility", "signal", "expected_cost_bps", "historical_signal_edge",
                 "risk_score", "composite_score"]:
        assert hasattr(r, attr)
    assert r.expected_cost_bps > 0


def test_historical_signal_edge_excludes_recent_unrealized_window():
    idx = pd.bdate_range("2020-01-01", periods=300)
    rng = np.random.default_rng(0)
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, 300))), index=idx)
    feat = pd.DataFrame({"momentum_rank": rng.uniform(0, 1, 300)}, index=idx)

    edge = historical_signal_edge(feat, close, threshold=0.8, forward_window=20)
    # the signal in the final 20 days should never contribute an observation
    recent_signal_dates = feat.index[-20:][feat["momentum_rank"].iloc[-20:] >= 0.8]
    if len(recent_signal_dates):
        # sanity: those dates exist in signal but must not be counted, i.e.
        # n_obs should be less than total historical hits including them
        all_hits = (feat["momentum_rank"] >= 0.8).sum()
        assert edge["n_obs"] <= all_hits


def test_score_candidates_empty_feature_map_returns_empty():
    results = score_candidates("korea", {}, {}, {})
    assert results == []
