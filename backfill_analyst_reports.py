#!/usr/bin/env python3
"""Backfill analyst-report metadata into the ignored local archive.

No report body/PDF is saved. The output is normalized metadata only and
lives under data/analyst_reports/, which is git-ignored by design.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path
import sys

import pandas as pd

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/"src"))

from quant.collectors.report_collector import (
    FinnhubAnalystCollector,
    NaverResearchCollector,
    YahooAnalystCollector,
    dedupe_reports,
)


def _symbols(value: str | None) -> list[str]:
    if not value:
        return []
    path=Path(value)
    if path.is_file():
        return [x.strip() for x in path.read_text(encoding="utf-8").replace("\n",",").split(",") if x.strip()]
    return [x.strip() for x in value.split(",") if x.strip()]


def _merge_write(path: Path, reports) -> int:
    rows=[asdict(r) for r in dedupe_reports(reports)]
    frame=pd.DataFrame(rows)
    if path.exists():
        old=pd.read_csv(path,dtype={"symbol":str})
        frame=pd.concat([old,frame],ignore_index=True)
        keys=["source","market","symbol","published_at","institution","analyst","rating","target_price","is_consensus"]
        available=[k for k in keys if k in frame.columns]
        frame=frame.drop_duplicates(subset=available,keep="last")
    path.parent.mkdir(parents=True,exist_ok=True)
    frame.to_csv(path,index=False)
    return len(frame)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--market",choices=["korea","us","both"],default="both")
    ap.add_argument("--symbols",help="Comma list or text file; required for US.")
    ap.add_argument("--max-pages",type=int,default=0,help="Naver pages; 0 means crawl until exhausted.")
    ap.add_argument("--us-start",default="2000-01-01")
    ap.add_argument("--output-dir",default="data/analyst_reports")
    args=ap.parse_args()
    outdir=Path(args.output_dir)
    symbols=_symbols(args.symbols)

    if args.market in {"korea","both"}:
        rows=NaverResearchCollector().collect(
            symbols or None,
            max_pages=None if args.max_pages==0 else args.max_pages,
        )
        n=_merge_write(outdir/"naver_research_metadata.csv",rows)
        print(f"Korea metadata archive: {n} rows")

    if args.market in {"us","both"}:
        if not symbols:
            if args.market=="us":
                ap.error("--symbols is required for US backfill")
            print("US backfill skipped: no --symbols provided")
        else:
            rows=[]
            rows.extend(YahooAnalystCollector().collect(symbols,max_actions=None))
            rows.extend(FinnhubAnalystCollector().collect(symbols,start=args.us_start))
            n=_merge_write(outdir/"us_analyst_metadata.csv",rows)
            print(f"US metadata archive: {n} rows")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
