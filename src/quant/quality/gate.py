"""Fail-Closed decision gate (spec section 2).

A thin, deliberately dumb wrapper around `DataQualityReport.overall_status`
-- kept as a separate function (rather than inlined at every call site) so
every caller (the scanner, `run_research.py`, `validate_data.py`,
dashboards) makes the fail-closed decision through the exact same one-line
rule, and so that rule is trivially unit-testable in isolation from the
full engine.
"""
from __future__ import annotations

from quant.quality.models import DataQualityReport


def may_proceed(report: DataQualityReport) -> tuple[bool, str]:
    """Whether the pipeline may generate today's candidates/signals from
    this market's data. Returns (allowed, reason)."""
    if report.overall_status != "PASS":
        failed = [c.check for c in report.mandatory_failures()]
        return False, (
            f"DATA VALIDATION FAILED for market={report.market} as_of={report.as_of}: "
            f"mandatory check(s) failed: {failed}. "
            "No investment candidates will be generated from this data."
        )
    return True, f"Data validation PASSED for market={report.market} as_of={report.as_of}."
