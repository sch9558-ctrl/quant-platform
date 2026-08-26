import pandas as pd
import pytest

from quant.data.store import ParquetCache, cached_get_ohlcv
from quant.data.synthetic_provider import SyntheticDataProvider


@pytest.fixture
def cache(tmp_path):
    return ParquetCache(market="korea", base_dir=tmp_path)


@pytest.fixture
def provider():
    return SyntheticDataProvider(market="korea", n_symbols=3, n_etfs=0,
                                  start="2020-01-01", end="2021-12-31", seed=7)


def test_save_and_load_roundtrip(cache):
    idx = pd.bdate_range("2022-01-01", periods=5)
    df = pd.DataFrame({
        "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "volume": 100, "adj_close": 1.0,
    }, index=idx)
    cache.save("SYM", df)
    loaded = cache.load("SYM")
    pd.testing.assert_frame_equal(loaded, df, check_freq=False)


def test_load_missing_returns_none(cache):
    assert cache.load("NOPE") is None


def test_upsert_merges_without_duplicating(cache):
    idx1 = pd.bdate_range("2022-01-01", periods=5)
    df1 = pd.DataFrame({"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "adj_close": 1}, index=idx1)
    cache.save("SYM", df1)

    idx2 = pd.bdate_range("2022-01-06", periods=5)  # overlaps last bday + adds new
    df2 = pd.DataFrame({"open": 2, "high": 2, "low": 2, "close": 2, "volume": 2, "adj_close": 2}, index=idx2)
    merged = cache.upsert("SYM", df2)

    assert merged.index.is_unique
    assert merged.index.is_monotonic_increasing


def test_cached_get_ohlcv_hits_cache_on_second_call(cache, provider):
    sym = provider.list_symbols()[0].symbol

    calls = {"n": 0}
    orig = provider.get_ohlcv

    def counting_get_ohlcv(symbol, start, end):
        calls["n"] += 1
        return orig(symbol, start, end)

    provider.get_ohlcv = counting_get_ohlcv

    df1 = cached_get_ohlcv(provider, cache, sym, "2020-01-01", "2020-06-30")
    assert not df1.empty
    assert calls["n"] == 1

    # second call for a fully-covered sub-range should not hit provider again
    df2 = cached_get_ohlcv(provider, cache, sym, "2020-02-01", "2020-05-31")
    assert calls["n"] == 1
    assert not df2.empty
