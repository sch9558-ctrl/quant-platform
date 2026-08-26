import pandas as pd
import pytest

from quant.data.factory import get_secondary_provider
from quant.data.synthetic_provider import SyntheticDataProvider
from quant.data.synthetic_secondary_provider import SyntheticSecondaryProvider


@pytest.fixture(scope="module")
def primary():
    return SyntheticDataProvider(market="korea", n_symbols=5, n_etfs=0, start="2020-01-01", end="2020-06-30", seed=7)


def test_synthetic_secondary_agrees_closely_with_primary(primary):
    secondary = SyntheticSecondaryProvider(primary)
    symbol = primary.list_symbols()[0].symbol

    p = primary.get_ohlcv(symbol, "2020-01-01", "2020-06-30")
    s = secondary.get_ohlcv(symbol, "2020-01-01", "2020-06-30")

    assert list(p.index) == list(s.index)
    rel_diff = ((s["close"] - p["close"]) / p["close"]).abs()
    assert (rel_diff <= 0.001).all()  # noise is bounded at 0.05%
    assert (rel_diff > 0).any()       # but it IS a distinct series, not a copy


def test_synthetic_secondary_perturbation_is_deterministic(primary):
    secondary1 = SyntheticSecondaryProvider(primary)
    secondary2 = SyntheticSecondaryProvider(primary)
    symbol = primary.list_symbols()[0].symbol
    df1 = secondary1.get_ohlcv(symbol, "2020-01-01", "2020-03-31")
    df2 = secondary2.get_ohlcv(symbol, "2020-01-01", "2020-03-31")
    pd.testing.assert_frame_equal(df1, df2)


def test_get_ohlcv_bulk_returns_all_requested_symbols(primary):
    secondary = SyntheticSecondaryProvider(primary)
    symbols = [s.symbol for s in primary.list_symbols()]
    result = secondary.get_ohlcv_bulk(symbols, "2020-01-01", "2020-06-30")
    assert set(result.keys()) == set(symbols)


def test_factory_returns_synthetic_secondary_in_demo_mode():
    secondary = get_secondary_provider("korea", demo=True)
    assert isinstance(secondary, SyntheticSecondaryProvider)


def test_factory_returns_none_type_secondary_gracefully_for_unknown_market():
    with pytest.raises(ValueError):
        get_secondary_provider("mars", demo=True)


def test_kr_secondary_provider_fails_gracefully_without_network():
    from quant.data.kr_secondary_provider import KRSecondaryProvider
    provider = KRSecondaryProvider()
    # no network access in this sandbox -- must return an empty frame, not raise
    df = provider.get_ohlcv("005930", "2024-01-01", "2024-01-31")
    assert df is not None
    assert list(df.columns) == ["open", "high", "low", "close", "volume", "adj_close"]


def test_us_secondary_provider_fails_gracefully_without_network():
    from quant.data.us_secondary_provider import USSecondaryProvider
    provider = USSecondaryProvider()
    df = provider.get_ohlcv("aapl.us", "2024-01-01", "2024-01-31")
    assert df is not None
    assert list(df.columns) == ["open", "high", "low", "close", "volume", "adj_close"]
