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


#: Reason strings are rendered verbatim on the dashboard, which is a
#: Korean-language UI, so they are written in Korean. The English term is
#: kept in parentheses wherever it names a concept the rest of the codebase
#: and the config files use (Out-of-Sample, Walk-Forward, ...), so a reader
#: can still map a reason back to the module that produced it.
_TEST_BUCKET_LABELS_KO = {
    "unit": "단위 테스트",
    "integration": "통합 테스트",
    "pipeline": "핵심 파이프라인 테스트",
}


def assess_readiness(inputs: ReadinessInputs) -> ReadinessResult:
    if not inputs.data_quality_pass or not inputs.no_unresolved_critical_data_anomaly:
        return ReadinessResult("DATA_INVALID", [
            "필수 데이터 검증에 실패했거나, 해결되지 않은 심각한 데이터 이상이 있습니다. "
            "이 상태에서는 투자 후보를 생성하지 않습니다."
        ])

    if not (inputs.unit_tests_pass and inputs.integration_tests_pass and inputs.critical_pipeline_tests_pass):
        missing = [label for key, label in _TEST_BUCKET_LABELS_KO.items() if not {
            "unit": inputs.unit_tests_pass,
            "integration": inputs.integration_tests_pass,
            "pipeline": inputs.critical_pipeline_tests_pass,
        }[key]]
        return ReadinessResult("DATA_VERIFIED", [
            "데이터는 정상이지만, 아직 통과하지 못한 소프트웨어 테스트가 있습니다: "
            + ", ".join(missing)
        ])

    if not (inputs.oos_validation_pass and inputs.walk_forward_pass):
        return ReadinessResult("RESEARCH_VALIDATED", [
            "아직 표본외(Out-of-Sample) / 워크포워드(Walk-Forward) 검증을 통과한 전략이 없습니다. "
            "전략을 만들 때 쓰지 않은 기간에서도 성과가 유지되는지 확인되기 전까지는 이 단계에 머무릅니다."
        ])

    if not (inputs.cost_stress_test_pass and inputs.overfitting_risk_acceptable):
        return ReadinessResult("OOS_VALIDATED", [
            "거래비용 스트레스 테스트를 통과하지 못했거나, 과최적화(overfitting) 위험이 "
            "허용 범위를 넘습니다."
        ])

    if inputs.paper_trading_sessions < inputs.required_paper_trading_sessions:
        return ReadinessResult(
            "PAPER_TRADING",
            [f"모의투자 진행 중입니다: {inputs.paper_trading_sessions}/{inputs.required_paper_trading_sessions} "
             "거래일 완료. 실제로 흘러간 거래일만 세며, 과거 데이터로 소급해서 채우지 않습니다."],
        )

    if not (inputs.no_unresolved_critical_software_error and inputs.risk_report_generated):
        return ReadinessResult("PAPER_VERIFIED", [
            "필요한 모의투자 기간은 채웠지만, 해결되지 않은 심각한 소프트웨어 오류가 있거나 "
            "리스크 보고서가 생성되지 않았습니다."
        ])

    return ReadinessResult(
        "ELIGIBLE_FOR_MANUAL_REVIEW",
        ["자동 검증 조건을 모두 충족했습니다. 그래도 실제 자금이 걸린 판단을 하기 전에는 "
         "반드시 사람(human)이 직접 검토해야 합니다. 이것은 매매 권유가 아니며, "
         "이 시스템은 스스로 실제 주문을 내지 않고 앞으로도 내지 않습니다."],
    )
