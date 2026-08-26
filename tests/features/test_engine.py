import pandas as pd
import pytest

from quant.data.synthetic_provider import SyntheticDataProvider
from quant.features.engine import FeatureEngine


@pytest.fixture(scope="module")
def provider():
    return SyntheticDataProvider(market="korea", n_symbols=10, n_etfs=0,
                                  start="2018-01-01", end="2022-12-31", seed=5)


def test_compute_panel_and_momentum_rank(provider):
    engine = FeatureEngine("korea")
    symbols = [s.symbol for s in provider.list_symbols()]
    ohlcv_map = {s: provider.get_ohlcv(s, "2018-01-01", "2022-12-31") for s in symbols}

    feat_map = engine.compute_panel(ohlcv_map)
    assert set(feat_map.keys()) == set(symbols)
    for df in feat_map.values():
        assert "ret_20d" in df.columns
        assert "sma_20" in df.columns
        assert "rsi_14" in df.columns

    rank_wide = engine.cross_sectional_momentum_rank(feat_map, ret_col="ret_120d")
    assert not rank_wide.empty
    # ranks on any given fully-populated date should span roughly (0, 1]
    last_row = rank_wide.dropna(how="all").iloc[-1].dropna()
    assert last_row.max() <= 1.0
    assert last_row.min() >= 0.0

    attached = engine.attach_momentum_rank(feat_map, rank_wide)
    for df in attached.values():
        assert "momentum_rank" in df.columns


def test_save_and_load_roundtrip(provider, tmp_path):
    engine = FeatureEngine("korea")
    sym = provider.list_symbols()[0].symbol
    ohlcv = provider.get_ohlcv(sym, "2018-01-01", "2022-12-31")
    feat = engine.compute_technical_features(ohlcv)

    engine.save(sym, feat, base_dir=tmp_path)
    loaded = engine.load(sym, base_dir=tmp_path)
    pd.testing.assert_frame_equal(loaded, feat, check_freq=False)
