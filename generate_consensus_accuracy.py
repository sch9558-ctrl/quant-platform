#!/usr/bin/env python3
"""Generate analyst/IB credibility JSON for current dashboard candidates."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from quant.analytics.analyst_consensus import AnalystTracker
from quant.collectors.report_collector import (
    CSVReportCollector,
    FinnhubAnalystCollector,
    NaverResearchCollector,
    YahooAnalystCollector,
    dedupe_reports,
)
from quant.data.factory import get_provider
from quant.utils.calendar import default_as_of


def _candidate_maps(dashboard: dict, max_symbols: int):
    symbols = {}
    prices = {}
    companies = {}
    for market in ("korea", "us"):
        section = dashboard.get("markets", {}).get(market) or {}
        candidates = section.get("candidates", [])[:max_symbols]
        symbols[market] = [str(c["symbol"]) for c in candidates]
        for c in candidates:
            key = f"{market}:{c['symbol']}"
            prices[key] = c.get("price")
            companies[key] = c.get("company")
    return symbols, prices, companies


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dashboard", default="site/data/dashboard.json")
    parser.add_argument("--output", default="site/data/consensus_accuracy.json")
    parser.add_argument("--archive-dir", default="data/analyst_reports")
    parser.add_argument("--max-symbols", type=int, default=20)
    args = parser.parse_args()

    dashboard = json.loads(Path(args.dashboard).read_text(encoding="utf-8"))
    symbols, current_prices, companies = _candidate_maps(
        dashboard, args.max_symbols
    )

    reports = []
    notes = []
    source_status = []

    archive = Path(args.archive_dir)
    archive_count = 0
    if archive.exists():
        for path in archive.glob("*.csv"):
            try:
                rows = CSVReportCollector().collect_file(str(path))
                reports.extend(rows)
                archive_count += len(rows)
            except Exception as exc:
                notes.append(f"{path.name} 읽기 실패: {exc}")
    source_status.append(
        {"source": "licensed_csv_archive", "ok": True, "records": archive_count}
    )

    if symbols["korea"]:
        try:
            rows = NaverResearchCollector().collect(symbols["korea"], max_pages=10)
            reports.extend(rows)
            source_status.append(
                {"source": "naver_finance", "ok": True, "records": len(rows)}
            )
        except Exception as exc:
            notes.append(f"네이버 리서치 메타데이터 수집 실패: {exc}")
            source_status.append(
                {"source": "naver_finance", "ok": False, "records": 0, "error": str(exc)}
            )

    if symbols["us"]:
        try:
            rows = YahooAnalystCollector().collect(symbols["us"])
            reports.extend(rows)
            source_status.append(
                {"source": "yahoo_finance", "ok": True, "records": len(rows)}
            )
        except Exception as exc:
            notes.append(f"Yahoo 애널리스트 메타데이터 수집 실패: {exc}")
            source_status.append(
                {"source": "yahoo_finance", "ok": False, "records": 0, "error": str(exc)}
            )
        try:
            rows = FinnhubAnalystCollector().collect(symbols["us"])
            reports.extend(rows)
            source_status.append(
                {"source": "finnhub", "ok": True, "records": len(rows)}
            )
        except Exception as exc:
            notes.append(f"Finnhub 메타데이터 수집 실패: {exc}")
            source_status.append(
                {"source": "finnhub", "ok": False, "records": 0, "error": str(exc)}
            )

    reports = dedupe_reports(reports)
    tracker = AnalystTracker()
    evaluations = []
    grouped = {}
    for report in reports:
        grouped.setdefault((report.market, report.symbol), []).append(report)

    for (market, symbol), rows in grouped.items():
        start = min(pd.Timestamp(r.published_at) for r in rows).strftime("%Y-%m-%d")
        end = default_as_of(market)
        try:
            prices = get_provider(market, demo=False).get_ohlcv(symbol, start, end)
        except Exception as exc:
            notes.append(f"{market}:{symbol} 가격 이력 실패: {exc}")
            continue
        for report in rows:
            evaluations.extend(tracker.evaluate_report(report, prices))

    aggregate = tracker.aggregate(evaluations)
    by_symbol = {}

    for (market, symbol), rows in grouped.items():
        key = f"{market}:{symbol}"
        ev = [
            e for e in evaluations
            if e.market == market and e.symbol == symbol
        ]
        targets = [
            r.target_price for r in rows
            if r.target_price is not None and not r.is_consensus
        ]
        consensus_targets = [
            r.target_price for r in rows
            if r.target_price is not None and r.is_consensus
        ]
        all_targets = targets or consensus_targets
        mean_target = (
            float(pd.Series(all_targets).mean()) if all_targets else None
        )
        current = current_prices.get(key)
        target_gap = (
            (mean_target / float(current) - 1) * 100
            if mean_target is not None and current not in (None, 0)
            else None
        )

        institution_rows = {}
        for report in rows:
            institution_rows.setdefault(report.institution, []).append(report)
        credible_sources = []
        for institution, inst_reports in institution_rows.items():
            inst_ev = [
                e for e in ev if e.institution == institution
            ]
            metric = tracker.credibility(inst_ev) if inst_ev else None
            inst_targets = [
                r.target_price for r in inst_reports
                if r.target_price is not None and not r.is_consensus
            ]
            if metric:
                credible_sources.append(
                    {
                        "institution": institution,
                        "credibility": metric,
                        "target_price_mean": (
                            float(pd.Series(inst_targets).mean())
                            if inst_targets else None
                        ),
                    }
                )
        credible_sources.sort(
            key=lambda x: (
                -x["credibility"]["sample_confidence"],
                -x["credibility"]["credibility_score"],
                -x["credibility"]["n_evaluable"],
            )
        )

        by_symbol[key] = {
            "market": market,
            "symbol": symbol,
            "company": companies.get(key),
            "current_price": current,
            "report_count": len(rows),
            "individual_target_count": len(targets),
            "consensus_target_count": len(consensus_targets),
            "target_price_mean": mean_target,
            "target_gap_pct": round(target_gap, 2) if target_gap is not None else None,
            "target_gap_label_ko": (
                "과열 주의"
                if target_gap is not None and target_gap >= 25
                else "보수적 목표"
                if target_gap is not None and target_gap <= -10
                else "중립 범위"
                if target_gap is not None
                else "목표가 표본 없음"
            ),
            "credibility": tracker.credibility(ev) if ev else None,
            "top_credible_sources": credible_sources[:5],
            "events": [
                e.to_dict()
                for e in ev
                if e.horizon == "3m"
            ][-80:],
        }

    payload = {
        "schema_version": 2,
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "coverage": {
            "korea_symbols": len(symbols["korea"]),
            "us_symbols": len(symbols["us"]),
            "reports": len(reports),
            "evaluations": len(evaluations),
            "mature_3m_evaluations": sum(
                1
                for e in evaluations
                if e.horizon == "3m" and (e.hit is not None or e.end_return_pct is not None)
            ),
        },
        "source_status": source_status,
        "overall": aggregate["overall"],
        "institutions": aggregate["institutions"][:50],
        "analysts": aggregate["analysts"][:50],
        "by_symbol": by_symbol,
        "source_notes_ko": notes + [
            "리포트 원문/PDF는 저장하지 않고 날짜·기관·투자의견·목표가 메타데이터만 분석합니다.",
            "최근 리포트는 평가기간이 끝나기 전까지 미적중으로 처리하지 않습니다.",
            "무료 공개 소스만으로 모든 과거 리포트 전수를 보장할 수 없습니다. 보유·라이선스 CSV를 data/analyst_reports에 추가하면 같은 기준으로 합산됩니다.",
        ],
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
