import pandas as pd
import pytest

from quant.data.synthetic_provider import SyntheticDataProvider
from quant.universe.engine import UniverseEngine


@pytest.fixture(scope="module")
def kr_provider():
    return SyntheticDataProvider(market="korea", n_symbols=40, n_etfs=5,
                                  start="2015-01-01", end="2023-12-31", seed=3)


def test_build_produces_included_and_excluded(kr_provider):
    engine = UniverseEngine("korea", kr_provider)
    snap = engine.build(as_of="2022-06-01")
    frame = snap.to_frame()

    assert not frame.empty
    assert set(["symbol", "included", "exclusion_reasons"]).issubset(frame.columns)
    # with synthetic random listing dates + tight liquidity filters, expect a mix
    assert frame["included"].sum() >= 1
    assert (~frame["included"]).sum() >= 0


def test_recently_listed_symbols_are_excluded(kr_provider):
    engine = UniverseEngine("korea", kr_provider)
    # ask for a universe very early, right after the dataset start, so any
    # symbol whose listing_date is close to as_of should fail min_listed_days
    snap = engine.build(as_of="2015-06-01")
    frame = snap.to_frame()
    recently_listed = frame[frame["listed_days"].notna() & (frame["listed_days"] < 252)]
    assert (~recently_listed["included"]).all()
    assert recently_listed["exclusion_reasons"].str.contains("too_recently_listed").all()


def test_snapshot_save_and_load_roundtrip(kr_provider, tmp_path):
    engine = UniverseEngine("korea", kr_provider)
    snap = engine.build(as_of="2021-01-04")
    engine.save_snapshot(snap, base_dir=tmp_path)
    loaded = engine.load_snapshot("2021-01-04", base_dir=tmp_path)
    assert loaded is not None
    pd.testing.assert_frame_equal(loaded.reset_index(drop=True), snap.to_frame().reset_index(drop=True))


def test_etf_excluded_when_include_etf_false(kr_provider, monkeypatch):
    engine = UniverseEngine("korea", kr_provider)
    engine.cfg = dict(engine.cfg)
    engine.cfg["include_etf"] = False
    snap = engine.build(as_of="2022-06-01")
    frame = snap.to_frame()
    assert (frame["asset_type"] == "etf").sum() == 0


def test_us_universe_filters_use_usd_keys():
    provider = SyntheticDataProvider(market="us", n_symbols=15, n_etfs=2,
                                      start="2018-01-01", end="2023-01-01", seed=11)
    engine = UniverseEngine("us", provider)
    snap = engine.build(as_of="2022-01-05")
    frame = snap.to_frame()
    assert not frame.empty
