#!/usr/bin/env python3
"""Generate metadata-only analyst credibility JSON for dashboard candidates."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parent; sys.path.insert(0,str(ROOT/"src"))
from quant.analytics.analyst_consensus import AnalystTracker
from quant.collectors.report_collector import CSVReportCollector,FinnhubAnalystCollector,NaverResearchCollector,YahooAnalystCollector
from quant.data.factory import get_provider
from quant.utils.calendar import default_as_of

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--dashboard",default="site/data/dashboard.json"); ap.add_argument("--output",default="site/data/consensus_accuracy.json"); ap.add_argument("--archive-dir",default="data/analyst_reports"); ap.add_argument("--max-symbols",type=int,default=20); args=ap.parse_args()
    dash=json.loads(Path(args.dashboard).read_text(encoding="utf-8")); reports=[]; notes=[]
    symbols={}
    for market in ("korea","us"):
        sec=dash.get("markets",{}).get(market) or {}
        symbols[market]=[c["symbol"] for c in sec.get("candidates",[])[:args.max_symbols]]
    ad=Path(args.archive_dir)
    if ad.exists():
        for p in ad.glob("*.csv"):
            try: reports.extend(CSVReportCollector().collect_file(str(p)))
            except Exception as e: notes.append(f"{p.name} 읽기 실패: {e}")
    if symbols["korea"]:
        try: reports.extend(NaverResearchCollector().collect(symbols["korea"]))
        except Exception as e: notes.append(f"네이버 리서치 메타데이터 수집 실패: {e}")
    if symbols["us"]:
        try: reports.extend(YahooAnalystCollector().collect(symbols["us"]))
        except Exception as e: notes.append(f"Yahoo 애널리스트 메타데이터 수집 실패: {e}")
        try: reports.extend(FinnhubAnalystCollector().collect(symbols["us"]))
        except Exception as e: notes.append(f"Finnhub 메타데이터 수집 실패: {e}")
    tracker=AnalystTracker(); evals=[]
    grouped={}
    for r in reports: grouped.setdefault((r.market,r.symbol),[]).append(r)
    for (market,symbol),rows in grouped.items():
        targets=[r for r in rows if r.target_price is not None]
        if not rows: continue
        start=min(pd.Timestamp(r.published_at) for r in rows).strftime("%Y-%m-%d"); end=default_as_of(market)
        try: prices=get_provider(market,demo=False).get_ohlcv(symbol,start,end)
        except Exception as e: notes.append(f"{market}:{symbol} 가격 이력 실패: {e}"); continue
        for r in rows: evals.extend(tracker.evaluate_report(r,prices))
    agg=tracker.aggregate(evals)
    by_symbol={}
    for (market,symbol),rows in grouped.items():
        ev=[e for e in evals if e.market==market and e.symbol==symbol]
        targets=[r.target_price for r in rows if r.target_price is not None]
        by_symbol[f"{market}:{symbol}"]={"market":market,"symbol":symbol,"report_count":len(rows),"target_price_mean":float(pd.Series(targets).mean()) if targets else None,"credibility":tracker.credibility(ev) if ev else None,"events":[e.to_dict() for e in ev if e.horizon=="3m"][-50:]}
    payload={"schema_version":1,"generated_at":pd.Timestamp.now(tz="UTC").isoformat(),"coverage":{"korea_symbols":len(symbols["korea"]),"us_symbols":len(symbols["us"]),"reports":len(reports),"evaluations":len(evals)},"overall":agg["overall"],"institutions":agg["institutions"][:50],"analysts":agg["analysts"][:50],"by_symbol":by_symbol,"source_notes_ko":notes+["리포트 원문/PDF는 저장하지 않고 메타데이터와 실현 주가만 분석합니다.","무료 공개 소스만으로 모든 과거 리포트 전수를 보장할 수 없으며, 보유/라이선스 CSV를 data/analyst_reports에 추가할 수 있습니다."]}
    out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8"); print(out); return 0
if __name__=="__main__": raise SystemExit(main())
