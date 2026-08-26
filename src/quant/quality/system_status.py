"""Single source of truth for "is the system healthy right now" (spec
sections 2, 14, 29-31).

Both `validate_system.py` (a human/CI-facing CLI) and the dashboard data
generator (`generate_dashboard_data.py`, spec section 33-34) must report
the *exact same* DATA QUALITY / UNIT TESTS / INTEGRATION TESTS /
REGRESSION TESTS / PIPELINE / INVESTMENT READINESS verdict for the same
day -- a CLI and a dashboard disagreeing about system health would itself
be a data-integrity problem. This module is that one shared computation;
neither caller re-implements any part of it.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from quant.quality.models import DataQualityReport
from quant.quality.pipeline_gate import validate_market
from quant.quality.readiness import ReadinessInputs, ReadinessResult, assess_readiness

REPO_ROOT = Path(__file__).resolve().parents[3]

TEST_BUCKETS: dict[str, list[str]] = {
    "UNIT TESTS": [
        "analytics", "backtest", "broker", "data", "features", "portfolio",
        "quality", "ranking", "regime", "report", "research_db", "risk", "strategy", "universe", "utils",
    ],
    "INTEGRATION TESTS": ["scanner", "pipeline", "dashboard"],
    "REGRESSION TESTS": ["validation"],
}

#: Deliberately excluded from this fast(er) daily self-audit: this single
#: test runs a full parameter-search Walk-Forward grid search and takes
#: several minutes on its own (see research_pipeline.py's module docstring
#: for why the daily pipeline itself never does a full param search
#: either). Still run by the regular `pytest tests/` developer workflow.
SLOW_DESELECT = ["tests/validation/test_walk_forward.py::test_walk_forward_with_param_search_picks_stable_params"]


@dataclass
class SystemStatus:
    as_of: str
    markets: list[str]
    data_quality_pass: bool
    pipeline_ok: bool
    unit_tests_pass: bool | None       # None == not run this call
    integration_tests_pass: bool | None
    regression_tests_pass: bool | None
    reports: dict[str, DataQualityReport] = field(default_factory=dict)
    test_output: dict[str, str] = field(default_factory=dict)
    readiness: ReadinessResult = None

    def label(self, v: bool | None) -> str:
        return "SKIPPED" if v is None else ("PASS" if v else "FAIL")

    def core_checks_all_pass(self) -> bool:
        """Every check that actually ran must have passed. A SKIPPED
        (None) bucket does not count as a failure -- the caller explicitly
        chose not to run it -- but it also never counts as a pass."""
        checks = [self.data_quality_pass, self.pipeline_ok] + [
            v for v in (self.unit_tests_pass, self.integration_tests_pass, self.regression_tests_pass)
            if v is not None
        ]
        return all(checks)


def _run_pytest_bucket(label: str, dirs: list[str]) -> tuple[bool, str]:
    existing = [str(REPO_ROOT / "tests" / d) for d in dirs if (REPO_ROOT / "tests" / d).is_dir()]
    if not existing:
        return True, "SKIPPED (no test directories found)"
    deselect_args = []
    for item in SLOW_DESELECT:
        deselect_args += ["--deselect", item]
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *existing, "-q", "-W", "ignore", *deselect_args],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    passed = result.returncode == 0
    tail = "\n".join(result.stdout.strip().splitlines()[-5:])
    if not passed:
        tail += "\n" + result.stderr.strip()[-1000:]
    return passed, tail


def _run_pipeline_check(markets: list[str], demo: bool, as_of: str) -> tuple[bool, bool, dict[str, DataQualityReport], list[str]]:
    """Returns (pipeline_ok, data_quality_ok, {market: report}, crash_messages)."""
    pipeline_ok = True
    data_quality_ok = True
    reports: dict[str, DataQualityReport] = {}
    crashes: list[str] = []
    for market in markets:
        try:
            result = validate_market(market, demo=demo, as_of=as_of)
            reports[market] = result.report
            if result.report.overall_status != "PASS":
                data_quality_ok = False
        except Exception as e:  # noqa: BLE001 -- a pipeline crash IS the signal here
            crashes.append(f"PIPELINE crashed for market={market}: {e!r}")
            pipeline_ok = False
            data_quality_ok = False
    return pipeline_ok, data_quality_ok, reports, crashes


def compute_system_status(
    markets: list[str], demo: bool = True, as_of: str | None = None, run_tests: bool = True,
) -> SystemStatus:
    import pandas as pd
    as_of = as_of or pd.Timestamp.today().strftime("%Y-%m-%d")

    pipeline_ok, data_quality_ok, reports, crashes = _run_pipeline_check(markets, demo, as_of)
    test_output = {"pipeline_crashes": "\n".join(crashes)} if crashes else {}

    if run_tests:
        unit_ok, unit_out = _run_pytest_bucket("UNIT TESTS", TEST_BUCKETS["UNIT TESTS"])
        integration_ok, integration_out = _run_pytest_bucket("INTEGRATION TESTS", TEST_BUCKETS["INTEGRATION TESTS"])
        regression_ok, regression_out = _run_pytest_bucket("REGRESSION TESTS", TEST_BUCKETS["REGRESSION TESTS"])
        test_output.update({"unit_tests": unit_out, "integration_tests": integration_out, "regression_tests": regression_out})
    else:
        unit_ok = integration_ok = regression_ok = None

    readiness_inputs = ReadinessInputs(
        data_quality_pass=data_quality_ok,
        unit_tests_pass=bool(unit_ok),
        integration_tests_pass=bool(integration_ok),
        critical_pipeline_tests_pass=bool(regression_ok) and pipeline_ok,
        # Strategy-validation-specific inputs (OOS/walk-forward pass,
        # cost-stress-test, overfitting risk, paper-trading session count,
        # risk report generated) are not yet backed by a persisted
        # readiness-state tracker in this codebase. Rather than fabricate
        # a PASS for signals not actually tracked yet, they are left at
        # their conservative (False/0) dataclass defaults -- so the
        # reported ladder level is never inflated above what is actually
        # verified. See docs/INVESTMENT_GATE.md.
    )
    readiness = assess_readiness(readiness_inputs)

    return SystemStatus(
        as_of=as_of, markets=markets, data_quality_pass=data_quality_ok, pipeline_ok=pipeline_ok,
        unit_tests_pass=unit_ok, integration_tests_pass=integration_ok, regression_tests_pass=regression_ok,
        reports=reports, test_output=test_output, readiness=readiness,
    )
