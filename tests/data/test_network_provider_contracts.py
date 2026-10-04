"""Daily live-provider contract checks.

These tests intentionally touch external services. They complement, and do not
replace, the fast deterministic fake-provider tests in the other data test
modules.
"""
from __future__ import annotations

import os

import pandas as pd
import pytest

from quant.data.kr_data_go_provider import DataGoKrProvider
from quant.data.kr_provider import KRDataProvider
from quant.data.us_provider import USDataProvider
from quant.data.us_secondary_provider import USSecondaryProvider

pytestmark = pytest.mark.network

START = "2026-09-25"
END = "2026-10-01"


def test_live_data_go_kr_daily_snapshot_contract(tmp_path):
    key=os.getenv("DATA_GO_KR_SERVICE_KEY","").strip()
    assert key, "DATA_GO_KR_SERVICE_KEY is required for the scheduled network contract job"
    provider=DataGoKrProvider(
        service_key=key,
        cache_dir=tmp_path,
        request_sleep_sec=0,
    )
    df=provider.fetch_daily_snapshot(END)
    required={"date","ticker","open","high","low","close","volume","market_cap"}
    assert not df.empty
    assert required.issubset(df.columns)
    assert len(df) > 500
    assert pd.to_numeric(df["close"],errors="coerce").notna().mean() > .95


def test_live_pykrx_kospi_index_contract():
    df=KRDataProvider(request_sleep_sec=0).get_index_ohlcv("KOSPI",START,END)
    assert not df.empty
    assert {"open","high","low","close","volume","adj_close"}.issubset(df.columns)
    assert pd.to_numeric(df["close"],errors="coerce").dropna().gt(0).all()


def test_live_yfinance_sp500_index_contract():
    df=USDataProvider().get_index_ohlcv("SP500",START,END)
    assert not df.empty
    assert {"open","high","low","close","volume","adj_close"}.issubset(df.columns)
    assert pd.to_numeric(df["close"],errors="coerce").dropna().gt(0).all()


def test_live_stooq_us_secondary_contract():
    df=USSecondaryProvider().get_ohlcv("AAPL",START,END)
    assert not df.empty, "Stooq returned no AAPL rows; cross-source provider contract is broken"
    assert list(df.columns)==["open","high","low","close","volume","adj_close"]
    assert float(df["close"].iloc[-1]) > 0
