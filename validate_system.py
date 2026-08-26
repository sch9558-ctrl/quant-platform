#!/usr/bin/env python3
"""System Validation CLI (spec sections 2, 14, 29-31: Daily Self-Audit +
Investment Readiness Gate).

Usage:
    python validate_system.py                      # both markets, today
    python validate_system.py --market korea --as-of 2026-08-26
    python validate_system.py --skip-tests          # fast: data+pipeline only

Prints six status lines:

    DATA QUALITY:        PASS/FAIL
    UNIT TESTS:           PASS/FAIL
    INTEGRATION TESTS:    PASS/FAIL
    REGRESSION TESTS:     PASS/FAIL
    PIPELINE:             PASS/FAIL
    INVESTMENT READINESS: <one of the 7 ladder levels>

DATA QUALITY  -- did every requested market's Data Quality Engine mandatory
                 checks pass (via quant.quality.pipeline_gate.validate_market,
                 the exact same gate the real pipeline uses)?
UNIT/INTEGRATION/REGRESSION TESTS -- three pytest sub-suites (see
                 `quant.quality.system_status.TEST_BUCKETS` for exactly
                 which directories map to which bucket).
PIPELINE      -- did the Provider -> Universe Engine -> Data Quality Engine
                 chain complete without raising an exception for every
                 requested market? (Distinct from DATA QUALITY: a market
                 can legitimately FAIL data quality while the pipeline
                 itself ran perfectly cleanly -- that is the Fail-Closed
                 gate working as designed, not a pipeline malfunction. A
                 pipeline CRASH is a different, more serious failure mode.)
INVESTMENT READINESS -- the 7-level ladder from quant.quality.readiness.
                 IMPORTANT HONESTY NOTE: the strategy-validation-specific
                 inputs (OOS/Walk-Forward pass, cost-stress-test pass,
                 overfitting risk, paper trading session count, risk
                 report generated) are not yet backed by a persisted
                 readiness-state tracker in this codebase (a follow-up
                 task). Rather than fabricate a PASS for signals not
                 actually tracked yet, these default to their
                 conservative/failing state, so the reported level is
                 never higher than what is actually verified -- it will
                 not exceed DATA_VERIFIED until that tracking is built.
                 See docs/INVESTMENT_GATE.md.

This script and `generate_dashboard_data.py` share the exact same
computation (`quant.quality.system_status.compute_system_status`) --
the CLI and the dashboard must never disagree about system health.

Exit code: 0 only if DATA QUALITY, all three test buckets, and PIPELINE are
all PASS. INVESTMENT READINESS is informational and never affects the exit
code by itself (an early-ladder level like DATA_VERIFIED is an entirely
expected, correct result on a system with a clean data/test pipeline that
just hasn't accumulated strategy-validation history yet -- it is not a
failure).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
_SRC = REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from quant.quality.system_status import compute_system_status  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--market", choices=["korea", "us", "both"], default="both")
    parser.add_argument("--as-of", default=None)
    parser.add_argument(
        "--demo", dest="demo", action="store_true", default=True,
        help="Use synthetic offline data (the default).",
    )
    parser.add_argument(
        "--real", dest="demo", action="store_false",
        help="Use REAL market data (pykrx / yfinance) instead of the synthetic "
             "offline dataset. Requires network access to KRX / Yahoo Finance.",
    )
    parser.add_argument("--skip-tests", action="store_true", help="Skip the pytest sub-suites (fast data+pipeline-only check).")
    args = parser.parse_args()

    markets = ["korea", "us"] if args.market == "both" else [args.market]
    print(f"System Validation -- markets={markets}\n")

    status = compute_system_status(markets, demo=args.demo, as_of=args.as_of, run_tests=not args.skip_tests)

    print(f"as_of={status.as_of}")
    print(f"DATA QUALITY: {'PASS' if status.data_quality_pass else 'FAIL'}")
    print(f"PIPELINE: {'PASS' if status.pipeline_ok else 'FAIL'}")
    if args.skip_tests:
        print("\n(--skip-tests set: UNIT/INTEGRATION/REGRESSION TESTS were not run)")
    else:
        print("")
        for name, key in (
            ("UNIT TESTS", "unit_tests_pass"), ("INTEGRATION TESTS", "integration_tests_pass"),
            ("REGRESSION TESTS", "regression_tests_pass"),
        ):
            print(f"{name}: {status.label(getattr(status, key))}")

    print("\n" + "=" * 60)
    print(f"DATA QUALITY:         {'PASS' if status.data_quality_pass else 'FAIL'}")
    print(f"UNIT TESTS:            {status.label(status.unit_tests_pass)}")
    print(f"INTEGRATION TESTS:     {status.label(status.integration_tests_pass)}")
    print(f"REGRESSION TESTS:      {status.label(status.regression_tests_pass)}")
    print(f"PIPELINE:              {'PASS' if status.pipeline_ok else 'FAIL'}")
    print(f"INVESTMENT READINESS:  {status.readiness.level}")
    for reason in status.readiness.reasons:
        print(f"  -> {reason}")
    print("")
    print(status.readiness.disclaimer)
    print("=" * 60)

    return 0 if status.core_checks_all_pass() else 1


if __name__ == "__main__":
    raise SystemExit(main())
