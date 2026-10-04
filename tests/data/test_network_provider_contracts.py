"""Daily live-provider contract checks.

These tests intentionally touch external services. They complement, and do not
replace, the fast deterministic fake-provider tests in the other data test
modules.
"""
from __future__ import annotations

import base64
import os
from urllib.parse import unquote

import pandas as pd
import pytest
import requests

from quant.data.kr_data_go_provider import DataGoKrProvider
from quant.data.kr_provider import KRDataProvider
from quant.data.us_provider import USDataProvider
from quant.data.us_secondary_provider import USSecondaryProvider
from quant.risk.market_traps import MarketTrapDataService
from quant.utils.calendar import last_n_trading_days, latest_closed_session

pytestmark = pytest.mark.network


def _session_window(market: str, n: int = 5) -> tuple[str, str]:
    end = latest_closed_session(market)
    days = last_n_trading_days(end.strftime("%Y-%m-%d"), n, market)
    assert len(days) == n, f"{market} calendar returned only {len(days)} closed sessions"
    return days[0].strftime("%Y-%m-%d"), days[-1].strftime("%Y-%m-%d")


def _validated_data_go_key() -> str:
    raw = os.getenv("DATA_GO_KR_SERVICE_KEY", "").strip()
    assert raw, (
        "DATA_GO_KR_SERVICE_KEY is required. Register it in GitHub repository "
        "Settings -> Secrets and variables -> Actions; issue the service key "
        "from data.go.kr."
    )
    key = unquote(raw).strip()
    length = len(key)
    assert length == 88, (
        f"DATA_GO_KR_SERVICE_KEY format is invalid (length {length}, expected 88). "
        "Register the complete key in GitHub Settings -> Secrets and variables -> Actions."
    )
    assert key.endswith("=="), (
        f"DATA_GO_KR_SERVICE_KEY format is invalid (length {length}, expected base64 padding '==')."
    )
    try:
        decoded = base64.b64decode(key, validate=True)
    except Exception as exc:
        pytest.fail(
            f"DATA_GO_KR_SERVICE_KEY format is invalid (length {length}, base64 decode failed: "
            f"{type(exc).__name__}); the key value is intentionally not printed."
        )
    assert len(decoded) == 64, (
        f"DATA_GO_KR_SERVICE_KEY format is invalid (length {length}, decoded bytes "
        f"{len(decoded)}, expected 64)."
    )
    return key


def _assert_krx_http_contract() -> None:
    url = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
    response = requests.get(url, timeout=15)
    content_type = str(response.headers.get("Content-Type", "")).lower()
    if response.status_code == 403:
        pytest.fail(
            f"KRX blocked this runner IP: HTTP 403, Content-Type={content_type or 'missing'}; "
            "do not treat the resulting pykrx parse error as a schema bug."
        )
    if "html" in content_type:
        pytest.fail(
            f"KRX returned HTML instead of a data response: HTTP {response.status_code}, "
            f"Content-Type={content_type}; pykrx cannot safely parse this runner response."
        )


def test_live_data_go_kr_daily_snapshot_contract(tmp_path):
    _, end = _session_window("korea")
    key = _validated_data_go_key()
    provider=DataGoKrProvider(
        service_key=key,
        cache_dir=tmp_path,
        request_sleep_sec=0,
    )
    df=provider.fetch_daily_snapshot(end)
    required={"date","ticker","open","high","low","close","volume","market_cap"}
    assert not df.empty
    assert required.issubset(df.columns)
    assert len(df) > 500
    assert pd.to_numeric(df["close"],errors="coerce").notna().mean() > .95


def test_live_pykrx_kospi_index_contract():
    start, end = _session_window("korea")
    _assert_krx_http_contract()
    df=KRDataProvider(request_sleep_sec=0).get_index_ohlcv("KOSPI",start,end)
    assert not df.empty
    assert {"open","high","low","close","volume","adj_close"}.issubset(df.columns)
    assert pd.to_numeric(df["close"],errors="coerce").dropna().gt(0).all()


def test_live_yfinance_sp500_index_contract():
    start, end = _session_window("us")
    df=USDataProvider().get_index_ohlcv("SP500",start,end)
    assert not df.empty
    assert {"open","high","low","close","volume","adj_close"}.issubset(df.columns)
    assert pd.to_numeric(df["close"],errors="coerce").dropna().gt(0).all()


def test_live_stooq_us_secondary_contract():
    start, end = _session_window("us")
    key=os.getenv("STOOQ_API_KEY","").strip()
    assert key, (
        "STOOQ_API_KEY is required. Register it in GitHub repository Settings -> "
        "Secrets and variables -> Actions as STOOQ_API_KEY; obtain the CSV API key "
        "from Stooq's data-download API key page."
    )
    df=USSecondaryProvider(api_key=key).get_ohlcv("AAPL",start,end)
    assert not df.empty, "Stooq returned no AAPL rows; cross-source provider contract is broken"
    assert list(df.columns)==["open","high","low","close","volume","adj_close"]
    assert float(df["close"].iloc[-1]) > 0


def test_live_yahoo_earnings_calendar_contract():
    _, end = _session_window("us")
    as_of = pd.Timestamp(end)
    result=MarketTrapDataService().fetch_us_earnings("AAPL",as_of=as_of)
    assert result.available is True, result.error
    assert pd.Timestamp(result.earnings_date) >= as_of


def test_live_kis_credit_ratio_contract():
    _, end = _session_window("korea")
    service=MarketTrapDataService()
    assert service.kis_configured, (
        "KIS_APP_KEY and KIS_APP_SECRET are required. Register both in GitHub "
        "repository Settings -> Secrets and variables -> Actions; issue them from "
        "the Korea Investment & Securities Open API developer portal."
    )
    result=service.fetch_kr_credit_ratio("005930",as_of=pd.Timestamp(end))
    assert result.available is True, result.error
    assert result.source=="KIS Open API daily credit balance"
    assert result.credit_balance_pct is not None
    assert 0.0 <= float(result.credit_balance_pct) <= 100.0
