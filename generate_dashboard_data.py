#!/usr/bin/env python3
"""Static Dashboard Data Generator (spec sections 5, 33-34).

Usage:
    python generate_dashboard_data.py [--as-of 2026-08-26] [--top-n 20] [--skip-tests]

Runs the full research pipeline (`run_full_pipeline`) plus the shared
system-health computation (`compute_system_status`) and writes:

    site/data/dashboard.json  -- today's full snapshot for the static
                                  dashboard (Overview / Data Quality /
                                  Korea Market / US Market / Strategies /
                                  Backtests / Paper Trading / Risk /
                                  Validation / Audit Log sections)
    site/data/history.json    -- one compact row appended per day for the
                                  30/90/365-day Long-term Validation
                                  History trend charts

Architecture (spec section 33): Python Research Pipeline -> JSON static
assets -> Static Dashboard Build (`build_dashboard.py`) -> GitHub Pages
deploy. No backend server, no paid hosting -- `site/` is a plain static
site GitHub Pages can serve as-is.

This script NEVER blocks on a market's data-validation failure -- a
Fail-Closed research result (blocked=True) still gets written into the
dashboard JSON, rendered as an explicit DATA VALIDATION FAILED state
(spec: "Research 실패 != Dashboard 배포 실패"). What IS Fail-Closed is
candidate generation itself (enforced upstream, inside run_full_pipeline);
this script's job is only to render whatever result that produced,
honestly.
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

from quant.dashboard_export.export import (  # noqa: E402
    append_history, build_dashboard_data, default_site_data_dir, write_dashboard_json,
)
from quant.pipeline.research_pipeline import run_full_pipeline  # noqa: E402
from quant.quality.system_status import compute_system_status  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument(
        "--demo", dest="demo", action="store_true", default=True,
        help="Use synthetic offline data (the default).",
    )
    parser.add_argument(
        "--real", dest="demo", action="store_false",
        help="Use REAL market data (pykrx / yfinance) instead of the synthetic "
             "offline dataset. Requires network access to KRX / Yahoo Finance.",
    )
    parser.add_argument(
        "--markets", nargs="+", choices=["korea", "us"], default=["korea", "us"],
        help="Which markets to run (default: both).",
    )
    parser.add_argument("--skip-tests", action="store_true", help="Skip the pytest sub-suites in the system-status check (faster).")
    parser.add_argument("--output-dir", default=None, help="Override site/data output directory.")
    parser.add_argument(
        "--allow-unpublishable", action="store_true",
        help="Write the payload even when it is synthetic or stale. For local "
             "development only -- never for production publication.",
    )
    args = parser.parse_args()

    as_of = args.as_of or pd.Timestamp.today().strftime("%Y-%m-%d")
    markets = tuple(dict.fromkeys(args.markets))

    print(f"Running research pipeline for as_of={as_of} ...")
    pipeline_result = run_full_pipeline(demo=args.demo, as_of=as_of, top_n=args.top_n, markets=markets)

    print("Computing system status (data quality + tests + pipeline + readiness) ...")
    status = compute_system_status(list(markets), demo=args.demo, as_of=as_of, run_tests=not args.skip_tests)

    data = build_dashboard_data(pipeline_result, status, demo=args.demo)

    output_dir = Path(args.output_dir) if args.output_dir else default_site_data_dir()

    # Fail-Closed for publication. Synthetic or stale data is never written
    # to the production data directory unless explicitly forced, because
    # that is exactly how a four-year-old synthetic snapshot ended up on
    # the public dashboard under a fresh `generated_at`.
    verdict = data.get("publishability", {})
    if not verdict.get("publishable") and not args.allow_unpublishable:
        print("\n대시보드 데이터를 게시하지 않았습니다 (게시 불가 상태):")
        for reason in verdict.get("reasons", []):
            print(f"  - {reason}")
        print(
            "\n실제 시장 데이터로 실행하려면 --real 을 사용하세요. "
            "합성 데이터를 의도적으로 기록하려면 --allow-unpublishable 을 사용하세요 "
            "(운영 게시용이 아닙니다)."
        )
        return 2

    dashboard_path = write_dashboard_json(
        data, output_dir, allow_unpublishable=args.allow_unpublishable)
    history_path = append_history(data, output_dir)

    print(f"\nWrote {dashboard_path}")
    print(f"Wrote {history_path}")
    print(f"\nOverview: {data['overview']}")
    return 0 if status.core_checks_all_pass() else 1


if __name__ == "__main__":
    raise SystemExit(main())
