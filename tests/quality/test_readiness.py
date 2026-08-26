from quant.quality.readiness import ReadinessInputs, assess_readiness


def _base(**overrides) -> ReadinessInputs:
    defaults = dict(
        data_quality_pass=True, unit_tests_pass=True, integration_tests_pass=True,
        critical_pipeline_tests_pass=True, oos_validation_pass=True, walk_forward_pass=True,
        cost_stress_test_pass=True, overfitting_risk_acceptable=True,
        paper_trading_sessions=250, required_paper_trading_sessions=250,
        risk_report_generated=True,
    )
    defaults.update(overrides)
    return ReadinessInputs(**defaults)


def test_data_invalid_when_data_quality_fails():
    result = assess_readiness(_base(data_quality_pass=False))
    assert result.level == "DATA_INVALID"


def test_data_verified_when_tests_incomplete():
    result = assess_readiness(_base(unit_tests_pass=False))
    assert result.level == "DATA_VERIFIED"


def test_research_validated_when_oos_not_passed():
    result = assess_readiness(_base(oos_validation_pass=False))
    assert result.level == "RESEARCH_VALIDATED"


def test_oos_validated_when_cost_stress_not_passed():
    result = assess_readiness(_base(cost_stress_test_pass=False))
    assert result.level == "OOS_VALIDATED"


def test_paper_trading_when_sessions_incomplete():
    result = assess_readiness(_base(paper_trading_sessions=10))
    assert result.level == "PAPER_TRADING"
    assert "10/250" in result.reasons[0]


def test_paper_verified_when_unresolved_error_exists():
    result = assess_readiness(_base(no_unresolved_critical_software_error=False))
    assert result.level == "PAPER_VERIFIED"


def test_eligible_for_manual_review_when_everything_passes():
    result = assess_readiness(_base())
    assert result.level == "ELIGIBLE_FOR_MANUAL_REVIEW"
    assert "human" in result.reasons[0].lower()


def test_disclaimer_always_present():
    for level_inputs in (_base(), _base(data_quality_pass=False)):
        result = assess_readiness(level_inputs)
        assert "100%" in result.disclaimer
        assert "does not mean" in result.disclaimer


def test_never_exceeds_eligible_for_manual_review():
    # even with every input maximized, the level enum itself has no rung
    # above ELIGIBLE_FOR_MANUAL_REVIEW -- this test documents that
    # invariant explicitly rather than leaving it implicit.
    result = assess_readiness(_base(paper_trading_sessions=99999, required_paper_trading_sessions=1))
    assert result.level == "ELIGIBLE_FOR_MANUAL_REVIEW"
    from quant.quality.readiness import Level
    import typing
    assert set(typing.get_args(Level)) == {
        "DATA_INVALID", "DATA_VERIFIED", "RESEARCH_VALIDATED", "OOS_VALIDATED",
        "PAPER_TRADING", "PAPER_VERIFIED", "ELIGIBLE_FOR_MANUAL_REVIEW",
    }
