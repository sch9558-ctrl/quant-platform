"""Investment Readiness Gate (spec sections 29-31).

A strictly one-way, strictly sequential ladder. Every level requires every
condition of the levels below it to still hold -- there is no path that
skips a level, and nothing in this module (or anywhere else in this
codebase) can push the result past `ELIGIBLE_FOR_MANUAL_REVIEW`. That
level's own name says what it is: eligible for a HUMAN to review, not
eligible to trade. Live trading is a separate, hard-locked switch entirely
(`quant.config.is_live_trading_enabled()`) that nothing in this module
touches or can influence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Level = Literal[
    "DATA_INVALID", "DATA_VERIFIED", "RESEARCH_VALIDATED", "OOS_VALIDATED",
    "PAPER_TRADING", "PAPER_VERIFIED", "ELIGIBLE_FOR_MANUAL_REVIEW",
]

DISCLAIMER = (
    "Data Validation 100% means all mandatory data-quality checks passed. "
    "It does not mean that future investment returns can be predicted with "
    "100% accuracy or that loss is impossible."
)

DEFAULT_REQUIRED_PAPER_TRADING_SESSIONS = 250


@dataclass
class ReadinessInputs:
    data_quality_pass: bool
    unit_tests_pass: bool = False
    integration_tests_pass: bool = False
    critical_pipeline_tests_pass: bool = False
    no_unresolved_critical_data_anomaly: bool = True
    oos_validation_pass: bool = False
    walk_forward_pass: bool = False
    cost_stress_test_pass: bool = False
    overfitting_risk_acceptable: bool = False
    paper_trading_sessions: int = 0
    required_paper_trading_sessions: int = DEFAULT_REQUIRED_PAPER_TRADING_SESSIONS
    no_unresolved_critical_software_error: bool = True
    risk_report_generated: bool = False


@dataclass
class ReadinessResult:
    level: Level
    reasons: list[str] = field(default_factory=list)
    disclaimer: str = DISCLAIMER

    def to_dict(self) -> dict:
        return {"level": self.level, "reasons": self.reasons, "disclaimer": self.disclaimer}


def assess_readiness(inputs: ReadinessInputs) -> ReadinessResult:
    if not inputs.data_quality_pass or not inputs.no_unresolved_critical_data_anomaly:
        return ReadinessResult("DATA_INVALID", ["Mandatory data validation failed, or an unresolved critical data anomaly exists."])

    if not (inputs.unit_tests_pass and inputs.integration_tests_pass and inputs.critical_pipeline_tests_pass):
        missing = [name for name, ok in (
            ("unit tests", inputs.unit_tests_pass),
            ("integration tests", inputs.integration_tests_pass),
            ("critical pipeline tests", inputs.critical_pipeline_tests_pass),
        ) if not ok]
        return ReadinessResult("DATA_VERIFIED", [f"Data is valid, but not all software tests pass yet: {missing}"])

    if not (inputs.oos_validation_pass and inputs.walk_forward_pass):
        return ReadinessResult("RESEARCH_VALIDATED", ["Out-of-Sample / Walk-Forward validation has not yet passed for a strategy."])

    if not (inputs.cost_stress_test_pass and inputs.overfitting_risk_acceptable):
        return ReadinessResult("OOS_VALIDATED", ["Transaction-cost stress test not passed, or overfitting risk is not at an acceptable level."])

    if inputs.paper_trading_sessions < inputs.required_paper_trading_sessions:
        return ReadinessResult(
            "PAPER_TRADING",
            [f"Paper trading in progress: {inputs.paper_trading_sessions}/{inputs.required_paper_trading_sessions} "
             "real trading sessions completed (counted in wall-clock time, never backfilled from historical data)."],
        )

    if not (inputs.no_unresolved_critical_software_error and inputs.risk_report_generated):
        return ReadinessResult("PAPER_VERIFIED", ["Required paper trading duration met, but an unresolved critical software error exists or the risk report has not been generated."])

    return ReadinessResult(
        "ELIGIBLE_FOR_MANUAL_REVIEW",
        ["All automated gate conditions are satisfied. This still requires a human to manually review before any real-money "
         "decision -- it is never a recommendation to trade, and this system does not and will not place real orders on its own."],
    )
