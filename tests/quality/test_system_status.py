from quant.quality.system_status import SystemStatus, compute_system_status


def test_compute_system_status_skip_tests_marks_buckets_as_none(tmp_path, monkeypatch):
    from quant import config as quant_config
    monkeypatch.setattr(quant_config, "resolve_path", lambda rel: tmp_path)

    status = compute_system_status(["korea"], demo=True, as_of="2022-06-01", run_tests=False)

    assert status.data_quality_pass is True
    assert status.pipeline_ok is True
    assert status.unit_tests_pass is None
    assert status.integration_tests_pass is None
    assert status.regression_tests_pass is None
    # Readiness must never claim a test bucket passed when it was never run.
    assert status.readiness.level == "DATA_VERIFIED"


def test_core_checks_all_pass_ignores_skipped_but_not_failures():
    status = SystemStatus(
        as_of="2022-06-01", markets=["korea"], data_quality_pass=True, pipeline_ok=True,
        unit_tests_pass=None, integration_tests_pass=None, regression_tests_pass=None,
        readiness=None,
    )
    assert status.core_checks_all_pass() is True  # all-skipped is not a failure

    status.data_quality_pass = False
    assert status.core_checks_all_pass() is False  # an actual failure still fails


def test_label_helper_distinguishes_skipped_from_pass_and_fail():
    status = SystemStatus(
        as_of="x", markets=[], data_quality_pass=True, pipeline_ok=True,
        unit_tests_pass=True, integration_tests_pass=False, regression_tests_pass=None, readiness=None,
    )
    assert status.label(status.unit_tests_pass) == "PASS"
    assert status.label(status.integration_tests_pass) == "FAIL"
    assert status.label(status.regression_tests_pass) == "SKIPPED"


def test_compute_system_status_blocked_market_yields_data_invalid(tmp_path, monkeypatch):
    from quant import config as quant_config
    from quant.quality import system_status as ss_module

    monkeypatch.setattr(quant_config, "resolve_path", lambda rel: tmp_path)

    class _FakeReport:
        overall_status = "FAIL"

    class _FakeResult:
        report = _FakeReport()

    monkeypatch.setattr(ss_module, "validate_market", lambda *a, **k: _FakeResult())

    status = compute_system_status(["korea"], demo=True, as_of="2022-06-01", run_tests=False)
    assert status.data_quality_pass is False
    assert status.readiness.level == "DATA_INVALID"
