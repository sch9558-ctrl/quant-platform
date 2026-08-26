#!/usr/bin/env python3
"""The single command that runs the entire Research Pipeline (spec section
35) end to end, for both Korea and US markets:

    1. Market data update
    2. Universe generation
    3. Feature computation
    4. Market regime detection
    5. Stock screening
    6. Major strategy evaluation (Walk-Forward Analysis)
    7. Update of previously-validated strategies
    8. Candidate stock ranking
    9. Risk analysis
   10. Research report generation

Usage:
    python run_research.py
    python run_research.py --markets korea
    python run_research.py --param-search      # slower, full parameter grid search per strategy
    python run_research.py --as-of 2026-08-25

By default this uses synthetic (offline) data, because this development
environment has no network access to KRX/Yahoo Finance -- see README.md
"Running with real data" for what changes when this is run on a machine
with internet access.

Runtime note: evaluating every enabled strategy via Walk-Forward Analysis
for one market typically takes a few minutes (synthetic data, ~25-60
symbols); both markets together is usually well under ten. Pass
`--param-search` only for a deliberate, slower deep-dive research run, not
routine daily use.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
_SRC = REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pandas as pd  # noqa: E402

from quant.pipeline.research_pipeline import run_full_pipeline  # noqa: E402
from quant.utils.logging import get_logger  # noqa: E402

logger = get_logger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--markets", nargs="+", choices=["korea", "us"], default=["korea", "us"])
    parser.add_argument("--top-n", type=int, default=20, help="Top-N candidates per market")
    parser.add_argument("--param-search", action="store_true",
                         help="Run the full parameter-stability grid search for every strategy (slow)")
    parser.add_argument(
        "--demo", action="store_true", default=True,
        help="Use synthetic offline data (default: on -- this sandbox has no network access to KRX/Yahoo).",
    )
    parser.add_argument("--as-of", default=None, help="Override the as-of date (YYYY-MM-DD); default: today.")
    args = parser.parse_args()

    as_of = args.as_of or pd.Timestamp.today().strftime("%Y-%m-%d")
    print(f"=== Research Pipeline run: as_of={as_of} markets={args.markets} "
          f"param_search={args.param_search} ===")

    t0 = time.time()
    result = run_full_pipeline(
        demo=args.demo, as_of=as_of, top_n=args.top_n,
        use_param_search=args.param_search, markets=tuple(args.markets),
    )
    elapsed = time.time() - t0

    for market, mr in result.markets.items():
        print(f"\n--- {market.upper()} ---")
        print(f"Universe size: {mr.scan.universe_size}  Top candidates: {len(mr.scan.top_candidates)}")
        if mr.scan.regime is not None:
            print(f"Regime: {mr.scan.regime.summary_label()}")
        print(f"Strategies evaluated: {len(mr.walk_forward_results)}  "
              f"(new: {len(mr.new_strategy_ids)}, updated: {len(mr.updated_strategy_ids)})")
        if not mr.ranking_df.empty:
            print("Top 3 strategies by composite score:")
            for sid, row in mr.ranking_df.head(3).iterrows():
                print(f"  {sid:20s} composite_score={row['composite_score']:.3f}")
        n_approved = sum(1 for c in mr.risk_checks if c["approved"])
        print(f"Portfolio allocation: {len(mr.portfolio_allocation.weights)} positions, "
              f"cash={mr.portfolio_allocation.cash_weight:.0%}  "
              f"(risk manager approved {n_approved}/{len(mr.risk_checks)} positions as-sized)")

    print(f"\nReport written to: {result.report_path}")
    print(f"Total elapsed: {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
