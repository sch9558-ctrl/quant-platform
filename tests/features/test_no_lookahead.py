"""Mechanical proof that FeatureEngine features do not use future data:
truncating the input OHLCV history at any cutoff date must not change any
feature value computed at or before that cutoff.
"""
import pandas as pd
import pytest

from quant.data.synthetic_provider import SyntheticDataProvider
from quant.features.engine import FeatureEngine


@pytest.fixture(scope="module")
def sample_ohlcv():
    provider = SyntheticDataProvider(market="korea", n_symbols=3, n_etfs=0,
                                      start="2015-01-01", end="2023-12-31", seed=42)
    sym = provider.list_symbols()[0].symbol
    return provider.get_ohlcv(sym, "2015-01-01", "2023-12-31")


@pytest.mark.parametrize("cutoff", ["2018-03-15", "2020-11-02", "2022-07-01"])
def test_technical_features_are_causal(sample_ohlcv, cutoff):
    engine = FeatureEngine("korea")
    full_feat = engine.compute_technical_features(sample_ohlcv)

    truncated_ohlcv = sample_ohlcv.loc[:cutoff]
    truncated_feat = engine.compute_technical_features(truncated_ohlcv)

    common_idx = truncated_feat.index
    aligned_full = full_feat.loc[common_idx]

    pd.testing.assert_frame_equal(aligned_full, truncated_feat, check_dtype=False, rtol=1e-9, atol=1e-9)


def test_relative_strength_is_also_causal(sample_ohlcv):
    engine = FeatureEngine("korea")
    bench = sample_ohlcv["close"] * 1.0  # any causal series works for this check

    cutoff = "2019-06-01"
    full_feat = engine.compute_technical_features(sample_ohlcv, benchmark_close=bench)
    truncated_feat = engine.compute_technical_features(sample_ohlcv.loc[:cutoff], benchmark_close=bench.loc[:cutoff])

    common_idx = truncated_feat.index
    pd.testing.assert_frame_equal(full_feat.loc[common_idx], truncated_feat, check_dtype=False, rtol=1e-9, atol=1e-9)
