#!/usr/bin/env python3
"""Network smoke test for the real market-data and report-metadata stack."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))

from quant.collectors.report_collector import NaverResearchCollector, YahooAnalystCollector
from quant.data.factory import get_provider
from quant.utils.calendar import default_as_of, is_trading_day


def main():
    result={"generated_at":pd.Timestamp.now(tz="UTC").isoformat(),"checks":{}}

    kr_expected=default_as_of("korea")
    assert is_trading_day(kr_expected,"korea")
    kr=get_provider("korea",demo=False)
    kr_asof=kr.resolve_as_of(kr_expected,max_lag_sessions=1) if hasattr(kr,"resolve_as_of") else kr_expected
    snap=kr.fetch_daily_snapshot(kr_asof)
    if len(snap)<1000:
        raise RuntimeError(f"Korea full-market snapshot unexpectedly small: {len(snap)} rows for {kr_asof}")
    result["checks"]["korea"]={
        "expected_as_of":kr_expected,
        "as_of":kr_asof,
        "provider_lag_sessions":0 if kr_asof==kr_expected else 1,
        "rows":int(len(snap)),
        "markets":sorted(snap["exchange"].dropna().unique().tolist()),
    }

    us_asof=default_as_of("us")
    assert is_trading_day(us_asof,"us")
    start=(pd.Timestamp(us_asof)-pd.Timedelta(days=14)).strftime("%Y-%m-%d")
    us=get_provider("us",demo=False)
    frames=us.get_ohlcv_bulk(["AAPL","NVDA"],start,us_asof)
    missing=[s for s in ("AAPL","NVDA") if s not in frames or frames[s].empty]
    if missing:
        raise RuntimeError(f"US OHLCV missing for {missing}")
    result["checks"]["us"]={"as_of":us_asof,"symbols":{s:int(len(frames[s])) for s in ("AAPL","NVDA")}}

    try:
        naver=NaverResearchCollector().collect(["005930"],max_pages=5)
        result["checks"]["naver_reports"]={"ok":True,"records":len(naver)}
    except Exception as exc:
        result["checks"]["naver_reports"]={"ok":False,"records":0,"error":str(exc)}

    try:
        yahoo=YahooAnalystCollector().collect(["NVDA"],max_actions=20)
        result["checks"]["yahoo_reports"]={"ok":True,"records":len(yahoo)}
    except Exception as exc:
        result["checks"]["yahoo_reports"]={"ok":False,"records":0,"error":str(exc)}

    print(json.dumps(result,ensure_ascii=False,indent=2))
    summary=Path(__import__("os").environ.get("GITHUB_STEP_SUMMARY",""))
    if str(summary) and summary.parent.exists():
        with summary.open("a",encoding="utf-8") as f:
            f.write("\n## Real Data Smoke\n")
            f.write(f"- 한국 expected {kr_expected} / actual {kr_asof}: {len(snap):,} rows\n")
            f.write(f"- 미국 {us_asof}: AAPL {len(frames['AAPL'])} bars / NVDA {len(frames['NVDA'])} bars\n")
            f.write(f"- 네이버 리포트(005930, 최근 5페이지): {result['checks']['naver_reports']['records']}건\n")
            f.write(f"- Yahoo 리포트(NVDA): {result['checks']['yahoo_reports']['records']}건\n")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
