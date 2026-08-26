import pandas as pd
import pytest

from quant.data.synthetic_provider import SyntheticDataProvider


@pytest.fixture(scope="module")
def kr_provider():
    return SyntheticDataProvider(market="korea", n_symbols=20, n_etfs=3,
                                  start="2018-01-01", end="2023-12-31", seed=1)


def test_list_symbols_nonempty(kr_provider):
    symbols = kr_provider.list_symbols()
    assert len(symbols) == 23
    equities = [s for s in symbols if s.asset_type == "equity"]
    etfs = [s for s in symbols if s.asset_type == "etf"]
    assert len(equities) == 20
    assert len(etfs) == 3
    assert all(s.market == "korea" for s in symbols)


def test_ohlcv_contract(kr_provider):
    sym = kr_provider.list_symbols()[0].symbol
    df = kr_provider.get_ohlcv(sym, "2019-01-01", "2019-12-31")
    assert not df.empty
    for col in ["open", "high", "low", "close", "volume", "adj_close"]:
        assert col in df.columns
    assert df.index.is_monotonic_increasing
    assert (df["high"] >= df["low"]).all()
    assert (df[["open", "high", "low", "close"]] > 0).all().all()


def test_ohlcv_respects_listing_date(kr_provider):
    # request a date range that starts well before the provider's own start;
    # no rows should exist before the symbol's simulated listing date
    sym = kr_provider.list_symbols()[-1].symbol
    info = kr_provider._symbols_info[sym]
    df = kr_provider.get_ohlcv(sym, "2000-01-01", "2023-12-31")
    if not df.empty:
        assert df.index.min() >= pd.Timestamp(info.listing_date)


def test_market_cap_and_fundamentals(kr_provider):
    equities = [s.symbol for s in kr_provider.list_symbols() if s.asset_type == "equity"][:5]
    caps = kr_provider.get_market_cap(equities, "2020-06-01")
    assert not caps.empty
    assert (caps > 0).all()

    fnd = kr_provider.get_fundamentals(equities, "2020-06-01")
    assert not fnd.empty
    assert "per" in fnd.columns


def test_index_ohlcv(kr_provider):
    idx = kr_provider.get_index_ohlcv("KOSPI", "2019-01-01", "2019-12-31")
    assert not idx.empty
    assert (idx["close"] > 0).all()


def test_deterministic_seed():
    p1 = SyntheticDataProvider(market="us", n_symbols=5, n_etfs=1, seed=99,
                                start="2020-01-01", end="2021-01-01")
    p2 = SyntheticDataProvider(market="us", n_symbols=5, n_etfs=1, seed=99,
                                start="2020-01-01", end="2021-01-01")
    sym = p1.list_symbols()[0].symbol
    df1 = p1.get_ohlcv(sym, "2020-01-01", "2021-01-01")
    df2 = p2.get_ohlcv(sym, "2020-01-01", "2021-01-01")
    pd.testing.assert_frame_equal(df1, df2)
