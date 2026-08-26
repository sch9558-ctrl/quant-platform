#!/usr/bin/env python3
"""Daily Market Scanner CLI (spec section 2 / CLI section 27).

Usage:
    python run_scan.py --market korea [--top-n 20] [--as-of 2026-08-26]
    python run_scan.py --market us --top-n 15

Runs Universe Engine -> Feature Engine -> Regime Detection -> Screener for
a single market and prints a human-readable candidate report to stdout
(the same `format_report` used by the dashboard's Market Scanner page).

This does not place, propose, or persist any order -- it is read-only
research output.
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
from quant.quality.pipeline_gate import run_gated_scan  # noqa: E402
from quant.scanner.scanner import format_report  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--market", choices=["korea", "us"], required=True)
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument(
        "--demo",
        action="store_true",
        default=True,
        help="Use synthetic offline data (default: on -- this sandbox has no network access to KRX/Yahoo).",
    )
    parser.add_argument("--as-of", default=None, help="Override the as-of date (YYYY-MM-DD); default: today.")
    args = parser.parse_args()

    as_of = args.as_of or pd.Timestamp.today().strftime("%Y-%m-%d")
    provider = get_provider(args.market, demo=args.demo)
    # Runs through the Fail-Closed Data Quality Engine gate first (spec
    # section 2) -- this is the same gate the research pipeline uses, so
    # `run_scan.py` can never show candidates built on data that failed
    # mandatory validation.
    gated = run_gated_scan(args.market, provider=provider, as_of=as_of, demo=args.demo, top_n=args.top_n)

    if gated.blocked:
        print("=" * 60)
        print("DATA VALIDATION: FAIL")
        print(f"⛔ {gated.block_reason}")
        print("오늘의 투자 후보 생성 중단 -- no candidates are shown below.")
        print("=" * 60)
        return 1

    print(format_report(gated.scan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
