#!/usr/bin/env python3
"""Standalone Daily Research Report generator (spec section 18 / CLI
section 27).

Usage:
    python generate_report.py [--as-of 2026-08-26] [--top-n 20]

Runs the Daily Market Scanner for both Korea and US, pulls the most recent
strategy ranking already on record in the Research DB (if any -- this does
NOT re-run Walk-Forward Analysis; use `run_research.py` for a full refresh
that also re-evaluates strategies), and writes a combined Markdown report
to the reports directory, printing its path.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
_SRC = REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pandas as pd  # noqa: E402

from quant.data.factory import get_provider  # noqa: E402
from quant.portfolio.constructor import PortfolioConstructor, PortfolioItem  # noqa: E402
from quant.quality.pipeline_gate import run_gated_scan  # noqa: E402
from quant.report.daily_report import generate_daily_report, save_report  # noqa: E402
from quant.research_db.db import ResearchDB  # noqa: E402


def _recent_ranking(db: ResearchDB, market: str) -> pd.DataFrame:
    df = db.query_experiments(market=market, limit=200)
    if df.empty:
        return df
    # keep only the latest row per strategy_id, sorted by composite_score
    df = df.sort_values("created_at", ascending=False).drop_duplicates("strategy_id")
    return df.sort_values("composite_score", ascending=False).set_index("strategy_id")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument(
        "--demo", action="store_true", default=True,
        help="Use synthetic offline data (default: on -- this sandbox has no network access to KRX/Yahoo).",
    )
    parser.add_argument("--as-of", default=None, help="Override the as-of date (YYYY-MM-DD); default: today.")
    args = parser.parse_args()

    as_of = args.as_of or pd.Timestamp.today().strftime("%Y-%m-%d")
    db = ResearchDB()

    # Every market's scan goes through the Fail-Closed Data Quality gate
    # (spec section 2) -- a market whose data failed mandatory validation
    # contributes no scan/candidates/allocation to this report; the report
    # still renders (dashboard 배포 is never blocked by a research
    # failure), just with an explicit DATA VALIDATION FAILED section for
    # that market instead of stale or fabricated candidates.
    scans = {}
    block_reasons = {}
    for market in ("korea", "us"):
        provider = get_provider(market, demo=args.demo)
        gated = run_gated_scan(market, provider=provider, as_of=as_of, demo=args.demo, top_n=args.top_n)
        scans[market] = gated.scan
        block_reasons[market] = gated.block_reason if gated.blocked else None

    combined_ranking = pd.concat(
        [r for r in (_recent_ranking(db, m) for m in ("korea", "us")) if not r.empty]
    ) if db.count() > 0 else pd.DataFrame()

    kr_scan = scans["korea"]
    allocation = None
    if kr_scan is not None:
        items = [
            PortfolioItem(
                symbol=c.symbol, market="korea", strategy_id="scanner", sector=None,
                signal_strength=max(c.composite_score, 0.0), volatility=c.volatility,
            )
            for c in kr_scan.top_candidates
        ]
        allocation = PortfolioConstructor().compute_weights(items)

    report_text = generate_daily_report(
        as_of=as_of, kr_scan=scans["korea"], us_scan=scans["us"],
        strategy_ranking=combined_ranking if not combined_ranking.empty else None,
        portfolio_allocation=allocation,
        kr_block_reason=block_reasons["korea"], us_block_reason=block_reasons["us"],
    )
    path = save_report(report_text, as_of)
    print(f"Report written to: {path}")
    print()
    print(report_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
