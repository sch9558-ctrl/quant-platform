from quant.quality.gate import may_proceed
from quant.quality.models import CheckResult, DataQualityReport


def _report(overall_status: str, mandatory_failed: bool = False) -> DataQualityReport:
    checks = [CheckResult("schema", mandatory=True, passed=not mandatory_failed)]
    return DataQualityReport(
        market="korea", as_of="2026-08-26", generated_at="2026-08-26T00:00:00Z",
        checks=checks, overall_status=overall_status,
        mandatory_validation_pass_rate=0.0 if mandatory_failed else 100.0,
    )


def test_pass_report_allows_proceeding():
    allowed, reason = may_proceed(_report("PASS"))
    assert allowed
    assert "PASSED" in reason


def test_fail_report_blocks_proceeding():
    allowed, reason = may_proceed(_report("FAIL", mandatory_failed=True))
    assert not allowed
    assert "DATA VALIDATION FAILED" in reason
    assert "schema" in reason
