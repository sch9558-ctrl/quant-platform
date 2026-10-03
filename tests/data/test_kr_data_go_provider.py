"""Contract tests for the data.go.kr V2 Korean primary provider."""
from __future__ import annotations
import pandas as pd
import pytest
import quant.data.kr_data_go_provider as krmod
from quant.data.kr_data_go_provider import DATA_GO_NUM_ROWS, DataGoKrProvider, MAX_DATA_GO_SNAPSHOT_SESSIONS

def _item(date="20261001", ticker="005930", market="KOSPI", close="105"):
    return {"basDt":date,"srtnCd":ticker,"itmsNm":"테스트종목","mrktCtg":market,"mkp":"100","hipr":"110","lopr":"90","clpr":close,"trqu":"1000","trPrc":"105000","mrktTotAmt":"1000000","fltRt":"1.2"}

class FakeResponse:
    text="{}"
    def __init__(self,items=None,total_count=None,result_code="00"):
        self.items=items if items is not None else [_item()]
        self.total_count=len(self.items) if total_count is None else total_count
        self.result_code=result_code
    def raise_for_status(self): pass
    def json(self):
        return {"response":{"header":{"resultCode":self.result_code,"resultMsg":"OK"},"body":{"totalCount":self.total_count,"items":{"item":self.items}}}}

def test_service_key_is_unquoted_once_and_full_market_request_is_single_page(tmp_path,monkeypatch):
    calls=[]
    def fake_get(url,params,timeout):
        calls.append((url,dict(params),timeout)); return FakeResponse([_item(),_item(ticker="247540",market="KOSDAQ")])
    monkeypatch.setattr(krmod.requests,"get",fake_get)
    p=DataGoKrProvider(service_key="abc%2Bdef%2Fghi%3D",cache_dir=tmp_path,request_sleep_sec=0)
    df=p.fetch_daily_snapshot("2026-10-01")
    assert p.service_key=="abc+def/ghi=" and len(calls)==1
    _,params,_=calls[0]
    assert params["serviceKey"]=="abc+def/ghi=" and params["numOfRows"]==str(DATA_GO_NUM_ROWS)=="3500"
    assert params["pageNo"]=="1" and params["basDt"]=="20261001"
    assert set(df["exchange"])=={"KOSPI","KOSDAQ"}

def test_verified_contract_maps_to_platform_fields_and_numeric_types(tmp_path,monkeypatch):
    monkeypatch.setattr(krmod.requests,"get",lambda *a,**k:FakeResponse())
    p=DataGoKrProvider(service_key="key",cache_dir=tmp_path,request_sleep_sec=0); df=p.fetch_daily_snapshot("20261001")
    assert {"date","ticker","open","high","low","close","volume","turnover","market_cap"}.issubset(df.columns)
    assert df.loc[0,"ticker"]=="005930" and pd.api.types.is_datetime64_any_dtype(df["date"])
    for c in ["open","high","low","close","volume","turnover","market_cap","change_pct"]: assert pd.api.types.is_numeric_dtype(df[c])

def test_missing_numeric_values_are_not_fabricated_as_zero(tmp_path,monkeypatch):
    item=_item(); item["clpr"]=""
    monkeypatch.setattr(krmod.requests,"get",lambda *a,**k:FakeResponse([item]))
    p=DataGoKrProvider(service_key="key",cache_dir=tmp_path,request_sleep_sec=0)
    assert pd.isna(p.fetch_daily_snapshot("20261001").loc[0,"close"])

def test_cache_prevents_duplicate_api_calls(tmp_path,monkeypatch):
    calls=0
    def fake_get(*a,**k):
        nonlocal calls; calls+=1; return FakeResponse()
    monkeypatch.setattr(krmod.requests,"get",fake_get)
    p=DataGoKrProvider(service_key="key",cache_dir=tmp_path,request_sleep_sec=0)
    a=p.fetch_daily_snapshot("2026-10-01"); b=p.fetch_daily_snapshot("20261001")
    assert calls==1 and (tmp_path/"kr_market_20261001.csv").is_file()
    pd.testing.assert_frame_equal(a.reset_index(drop=True),b.reset_index(drop=True),check_dtype=False)

def test_contract_drift_and_truncation_fail_closed(tmp_path,monkeypatch):
    bad=_item(); bad.pop("clpr")
    monkeypatch.setattr(krmod.requests,"get",lambda *a,**k:FakeResponse([bad]))
    p=DataGoKrProvider(service_key="key",cache_dir=tmp_path,request_sleep_sec=0)
    with pytest.raises(RuntimeError,match="missing fields"): p.fetch_daily_snapshot("20261001")
    p2=DataGoKrProvider(service_key="key",cache_dir=tmp_path/"b",request_sleep_sec=0)
    monkeypatch.setattr(krmod.requests,"get",lambda *a,**k:FakeResponse([_item()],total_count=DATA_GO_NUM_ROWS+1))
    with pytest.raises(RuntimeError,match="silently truncated"): p2.fetch_daily_snapshot("20261001")

def test_bulk_range_uses_one_snapshot_per_session_and_returns_symbol_frames(tmp_path,monkeypatch):
    sessions=pd.DatetimeIndex(["2026-10-01","2026-10-02","2026-10-05"]); monkeypatch.setattr(krmod,"trading_days",lambda *a,**k:sessions)
    p=DataGoKrProvider(service_key="key",cache_dir=tmp_path,request_sleep_sec=0); seen=[]
    def snap(ts):
        ts=pd.Timestamp(ts); seen.append(ts.strftime("%Y%m%d"))
        return pd.DataFrame({"date":[ts,ts],"ticker":["005930","247540"],"name":["삼성전자","에코프로비엠"],"exchange":["KOSPI","KOSDAQ"],"open":[100,200],"high":[110,220],"low":[90,180],"close":[105,210],"volume":[1000,500],"turnover":[105000,105000],"market_cap":[1e6,2e6],"change_pct":[1.2,-.5]})
    monkeypatch.setattr(p,"fetch_daily_snapshot",snap)
    out=p.get_ohlcv_bulk(["005930","247540"],"2026-10-01","2026-10-05")
    assert seen==["20261001","20261002","20261005"] and set(out)=={"005930","247540"}
    assert list(out["005930"].columns)==["open","high","low","close","volume","adj_close"] and len(out["005930"])==3

def test_list_symbols_and_market_cap_reuse_daily_snapshot(tmp_path,monkeypatch):
    p=DataGoKrProvider(service_key="key",cache_dir=tmp_path,request_sleep_sec=0)
    df=pd.DataFrame({"date":[pd.Timestamp("2026-10-01")]*2,"ticker":["005930","247540"],"name":["삼성전자","에코프로비엠"],"exchange":["KOSPI","KOSDAQ"],"open":[1,2],"high":[2,3],"low":[.5,1.5],"close":[1.5,2.5],"volume":[10,20],"turnover":[15,50],"market_cap":[123456.,654321.],"change_pct":[1,2]})
    monkeypatch.setattr(p,"fetch_daily_snapshot",lambda d:df)
    assert {(s.symbol,s.exchange) for s in p.list_symbols("2026-10-01")}=={("005930","KOSPI"),("247540","KOSDAQ")}
    assert p.get_market_cap(["005930","247540"],"2026-10-01").to_dict()=={"005930":123456.,"247540":654321.}

def test_long_uncached_history_uses_pykrx_fallback(tmp_path,monkeypatch):
    sessions=pd.bdate_range("2024-01-01",periods=MAX_DATA_GO_SNAPSHOT_SESSIONS+1); monkeypatch.setattr(krmod,"trading_days",lambda *a,**k:sessions)
    p=DataGoKrProvider(service_key="key",cache_dir=tmp_path,request_sleep_sec=0)
    monkeypatch.setattr(p,"fetch_daily_snapshot",lambda d:pytest.fail("snapshot path should not run"))
    expected=pd.DataFrame({"open":[1.],"high":[2.],"low":[.5],"close":[1.5],"volume":[10.],"adj_close":[1.5]},index=pd.DatetimeIndex(["2024-01-02"],name="date"))
    monkeypatch.setattr(krmod.KRDataProvider,"get_ohlcv",lambda *a,**k:expected.copy())
    assert set(p.get_ohlcv_bulk(["005930","000660"],"2024-01-01","2025-12-31"))=={"005930","000660"}

def test_missing_service_key_fails_closed(tmp_path,monkeypatch):
    monkeypatch.delenv("DATA_GO_KR_SERVICE_KEY",raising=False)
    p=DataGoKrProvider(service_key="",cache_dir=tmp_path,request_sleep_sec=0)
    with pytest.raises(RuntimeError,match="DATA_GO_KR_SERVICE_KEY"): p.fetch_daily_snapshot("20261001")


def test_publication_lag_uses_exact_pykrx_fallback(tmp_path, monkeypatch):
    p = DataGoKrProvider(service_key="key", cache_dir=tmp_path, request_sleep_sec=0)
    monkeypatch.setattr(
        p, "_request_daily_snapshot",
        lambda d: (_ for _ in ()).throw(
            RuntimeError(f"data.go.kr returned no rows for basDt={d}")
        ),
    )
    fallback = pd.DataFrame({
        "date": [pd.Timestamp("2026-10-02")],
        "ticker": ["005930"],
        "name": ["005930"],
        "exchange": ["KOSPI"],
        "open": [100.0], "high": [105.0], "low": [99.0], "close": [104.0],
        "volume": [1000.0], "turnover": [104000.0],
        "market_cap": [1e9], "change_pct": [1.0],
    })
    monkeypatch.setattr(p, "_pykrx_exact_snapshot", lambda d: fallback.copy())
    out = p.fetch_daily_snapshot("2026-10-02")
    assert out["date"].max() == pd.Timestamp("2026-10-02")
    assert out.loc[0, "ticker"] == "005930"


def test_contract_error_does_not_fallback_to_pykrx(tmp_path, monkeypatch):
    p = DataGoKrProvider(service_key="key", cache_dir=tmp_path, request_sleep_sec=0)
    monkeypatch.setattr(
        p, "_request_daily_snapshot",
        lambda d: (_ for _ in ()).throw(RuntimeError("response contract changed")),
    )
    monkeypatch.setattr(
        p, "_pykrx_exact_snapshot",
        lambda d: pytest.fail("contract drift must fail closed"),
    )
    with pytest.raises(RuntimeError, match="contract changed"):
        p.fetch_daily_snapshot("2026-10-02")
