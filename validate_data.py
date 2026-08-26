#!/usr/bin/env python3
"""Data Validation CLI (spec sections 2, 14, 33: "Data Validation 100%").

Usage:
    python validate_data.py                       # both markets, today
    python validate_data.py --market korea
    python validate_data.py --market us --as-of 2026-08-26
    python validate_data.py --no-secondary         # skip cross-source check

Runs the full Data Quality Engine (Provider -> Universe Engine -> schema /
OHLC integrity / duplicate / missing-session / freshness / timezone /
outlier / corporate-action / cross-source validation -> Canonical Data)
for one or both markets via `quant.quality.pipeline_gate.validate_market`,
and prints an unambiguous verdict:

    DATA VALIDATION: PASS
    DATA VALIDATION: FAIL

This is the SAME gate `run_scan.py`, `run_paper.py`, and the research
pipeline use to decide whether to generate candidates -- this script never
invents its own, looser notion of "the data looks fine".

IMPORTANT (spec section 0): "DATA VALIDATION: PASS" means every mandatory
data-quality check passed. It is NOT a statement about whether any
strategy built on this data will be profitable, and no partial credit is
given -- a single mandatory check failing (even at 99.99% of rows passing)
makes the whole run FAIL. See docs/DATA_VALIDATION.md.

Exit code: 0 if every requested market's DATA VALIDATION is PASS, 1
otherwise -- suitable for `python validate_data.py || exit 1` in a CI step
or the daily GitHub Actions pipeline.
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

from quant.quality.pipeline_gate import validate_market  # noqa: E402


def _print_market_report(market: str, result) -> bool:
    report = result.report
    print(f"\n=== {market.upper()} -- as_of={report.as_of} ===")
    print(f"Data Version:        {report.data_version}")
    print(f"Symbols Checked:     {report.n_symbols_checked}")
    print(f"Mandatory Pass Rate: {report.mandatory_validation_pass_rate:.2f}%  (binary -- no partial credit)")
    print(f"Data Integrity Score:{report.data_integrity_score:.4f}  (informational only, NOT a prediction of returns)")
    print("")
    print(f"{'CHECK':<28}{'MANDATORY':<12}{'RESULT':<8}ISSUES")
    for c in report.checks:
        result_str = "PASS" if c.passed else "FAIL"
        print(f"{c.check:<28}{'yes' if c.mandatory else 'no':<12}{result_str:<8}{len(c.issues)}")

    passed = report.overall_status == "PASS"
    print("")
    print(f"[{market}] DATA VALIDATION: {'PASS' if passed else 'FAIL'}")
    if not passed:
        for c in report.mandatory_failures():
            print(f"  - FAILED (mandatory): {c.check}")
            for issue in c.issues[:5]:
                print(f"      {issue.severity}: {issue.message}")
            if len(c.issues) > 5:
                print(f"      ... and {len(c.issues) - 5} more")
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--market", choices=["korea", "us", "both"], default="both")
    parser.add_argument("--as-of", default=None, help="Override the as-of date (YYYY-MM-DD); default: today.")
    parser.add_argument("--lookback-days", type=int, default=400)
    parser.add_argument(
        "--demo", action="store_true", default=True,
        help="Use synthetic offline data (default: on -- this sandbox has no network access to KRX/Yahoo).",
    )
    parser.add_argument("--no-secondary", action="store_true", help="Skip cross-source (secondary provider) validation.")
    args = parser.parse_args()

    as_of = args.as_of or pd.Timestamp.today().strftime("%Y-%m-%d")
    markets = ["korea", "us"] if args.market == "both" else [args.market]

    all_passed = True
    for market in markets:
        result = validate_market(
            market, demo=args.demo, as_of=as_of, lookback_days=args.lookback_days,
            use_secondary=not args.no_secondary,
        )
        market_passed = _print_market_report(market, result)
        all_passed = all_passed and market_passed

    print("\n" + "=" * 40)
    print(f"DATA VALIDATION: {'PASS' if all_passed else 'FAIL'}")
    print("=" * 40)
    print(
        "\nReminder: \"Data Validation PASS\" means all mandatory data-quality "
        "checks passed. It does not mean future investment returns can be "
        "predicted, or that loss is impossible."
    )
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
