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
                 `_TEST_BUCKETS` below for exactly which directories map to
                 which bucket).
PIPELINE      -- did the Provider -> Universe Engine -> Data Quality Engine
                 chain complete without raising an exception for every
                 requested market? (Distinct from DATA QUALITY: a market
                 can legitimately FAIL data quality while the pipeline
                 itself ran perfectly cleanly -- that is the Fail-Closed
                 gate working as designed, not a pipeline malfunction. A
                 pipeline CRASH is a different, more serious failure mode.)
INVESTMENT READINESS -- the 7-level ladder from quant.quality.readiness,
                 fed by the statuses above. IMPORTANT HONESTY NOTE: the
                 strategy-validation-specific inputs (OOS/Walk-Forward
                 pass, cost-stress-test pass, overfitting risk, paper
                 trading session count, risk report generated) are not yet
                 backed by a persisted readiness-state tracker in this
                 codebase (that is a follow-up task -- a strategy's
                 walk-forward/OOS results live in ResearchDB per
                 experiment, and paper-trading session counts need a
                 dedicated wall-clock session counter, neither of which is
                 wired into this script yet). Rather than fabricate a
                 PASS for signals we do not actually track yet, this
                 script defaults them to their conservative/failing state,
                 so the reported level is never higher than what is
                 actually verified -- it will not exceed DATA_VERIFIED
                 until that tracking is built. See docs/INVESTMENT_GATE.md.

Exit code: 0 only if DATA QUALITY, all three test buckets, and PIPELINE are
all PASS. INVESTMENT READINESS is informational and never affects the exit
code by itself (an early-ladder level like DATA_VERIFIED is an entirely
expected, correct result on a system with a clean data/test pipeline that
just hasn't accumulated strategy-validation history yet -- it is not a
failure).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
_SRC = REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pandas as pd  # noqa: E402

from quant.quality.pipeline_gate import validate_market  # noqa: E402
from quant.quality.readiness import ReadinessInputs, assess_readiness  # noqa: E402

_TEST_BUCKETS = {
    "UNIT TESTS": [
        "analytics", "backtest", "broker", "data", "features", "portfolio",
        "quality", "ranking", "regime", "report", "research_db", "risk", "strategy", "universe", "utils",
    ],
    "INTEGRATION TESTS": ["scanner", "pipeline", "dashboard"],
    "REGRESSION TESTS": ["validation"],
}


#: Deliberately excluded from the daily/CI-facing test run: this single
#: test runs a full parameter-search Walk-Forward grid search and takes
#: several minutes on its own (see research_pipeline.py's module docstring
#: for why the daily pipeline itself never does a full param search
#: either). It is still run by the regular `pytest tests/` developer
#: workflow -- just not by this fast(er) daily self-audit script.
_SLOW_DESELECT = ["tests/validation/test_walk_forward.py::test_walk_forward_with_param_search_picks_stable_params"]


def _run_pytest_bucket(label: str, dirs: list[str]) -> bool:
    existing = [str(REPO_ROOT / "tests" / d) for d in dirs if (REPO_ROOT / "tests" / d).is_dir()]
    if not existing:
        print(f"{label}: SKIPPED (no test directories found)")
        return True
    deselect_args = []
    for item in _SLOW_DESELECT:
        deselect_args += ["--deselect", item]
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *existing, "-q", "-W", "ignore", *deselect_args],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    passed = result.returncode == 0
    print(f"{label}: {'PASS' if passed else 'FAIL'}")
    tail = "\n".join(result.stdout.strip().splitlines()[-5:])
    print(f"  {tail}")
    if not passed:
        print(result.stderr.strip()[-1000:])
    return passed


def _run_pipeline_check(markets: list[str], demo: bool, as_of: str) -> tuple[bool, bool, dict]:
    """Returns (pipeline_ok, data_quality_ok, {market: report})."""
    pipeline_ok = True
    data_quality_ok = True
    reports = {}
    for market in markets:
        try:
            result = validate_market(market, demo=demo, as_of=as_of)
            reports[market] = result.report
            if result.report.overall_status != "PASS":
                data_quality_ok = False
        except Exception as e:  # noqa: BLE001 -- a pipeline crash IS the signal here
            print(f"  PIPELINE crashed for market={market}: {e!r}")
            pipeline_ok = False
            data_quality_ok = False
    return pipeline_ok, data_quality_ok, reports


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--market", choices=["korea", "us", "both"], default="both")
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--demo", action="store_true", default=True)
    parser.add_argument("--skip-tests", action="store_true", help="Skip the pytest sub-suites (fast data+pipeline-only check).")
    args = parser.parse_args()

    as_of = args.as_of or pd.Timestamp.today().strftime("%Y-%m-%d")
    markets = ["korea", "us"] if args.market == "both" else [args.market]

    print(f"System Validation -- as_of={as_of} markets={markets}\n")

    pipeline_ok, data_quality_ok, reports = _run_pipeline_check(markets, args.demo, as_of)
    print(f"DATA QUALITY: {'PASS' if data_quality_ok else 'FAIL'}")
    print(f"PIPELINE: {'PASS' if pipeline_ok else 'FAIL'}")

    if args.skip_tests:
        # `None` means "not run", deliberately distinct from True/False --
        # this script must never claim PASS for a check it did not
        # actually perform (spec: never hide a not-yet-verified state
        # behind a PASS label). `readiness_inputs` below treats None as
        # "not passed" (conservative), and the exit code ignores these
        # three buckets entirely rather than silently treating skip as ok.
        unit_ok = integration_ok = regression_ok = None
        print("\n(--skip-tests set: UNIT/INTEGRATION/REGRESSION TESTS were not run)")
    else:
        print("")
        unit_ok = _run_pytest_bucket("UNIT TESTS", _TEST_BUCKETS["UNIT TESTS"])
        integration_ok = _run_pytest_bucket("INTEGRATION TESTS", _TEST_BUCKETS["INTEGRATION TESTS"])
        regression_ok = _run_pytest_bucket("REGRESSION TESTS", _TEST_BUCKETS["REGRESSION TESTS"])

    def _label(v: bool | None) -> str:
        return "SKIPPED" if v is None else ("PASS" if v else "FAIL")

    readiness_inputs = ReadinessInputs(
        data_quality_pass=data_quality_ok,
        unit_tests_pass=bool(unit_ok),
        integration_tests_pass=bool(integration_ok),
        critical_pipeline_tests_pass=bool(regression_ok) and pipeline_ok,
        # Not yet backed by a persisted tracker -- see module docstring above.
        # Left at their conservative (False/0) defaults on purpose.
    )
    readiness = assess_readiness(readiness_inputs)

    print("\n" + "=" * 60)
    print(f"DATA QUALITY:         {'PASS' if data_quality_ok else 'FAIL'}")
    print(f"UNIT TESTS:            {_label(unit_ok)}")
    print(f"INTEGRATION TESTS:     {_label(integration_ok)}")
    print(f"REGRESSION TESTS:      {_label(regression_ok)}")
    print(f"PIPELINE:              {'PASS' if pipeline_ok else 'FAIL'}")
    print(f"INVESTMENT READINESS:  {readiness.level}")
    for reason in readiness.reasons:
        print(f"  -> {reason}")
    print("")
    print(readiness.disclaimer)
    print("=" * 60)

    # A bucket that was never run does not fail the exit code (the user
    # explicitly asked to skip it via --skip-tests) -- but it also never
    # counts as passing; only buckets that actually ran and failed do.
    core_checks = [data_quality_ok, pipeline_ok] + [v for v in (unit_ok, integration_ok, regression_ok) if v is not None]
    all_core_ok = all(core_checks)
    return 0 if all_core_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
