"""Structural guardrails for .github/workflows/daily-pipeline.yml (spec
sections 24-28). Not a GitHub Actions runner test -- these check the YAML
shape so a future edit can't silently break the schedule, the
idempotency guard, or the minimal-permissions requirement without a test
failing.
"""
from pathlib import Path

import yaml

WORKFLOW_PATH = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "daily-pipeline.yml"


def _load():
    with open(WORKFLOW_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_workflow_file_exists_and_parses():
    data = _load()
    assert "jobs" in data


def test_two_schedules_and_manual_dispatch():
    data = _load()
    on = data.get("on") or data.get(True)  # PyYAML parses bare `on:` as boolean True under YAML 1.1
    schedules = {entry["cron"] for entry in on["schedule"]}
    assert "0 22 * * *" in schedules, "missing 07:00 KST primary schedule (22:00 UTC)"
    assert "15 22 * * *" in schedules, "missing 07:15 KST recovery schedule (22:15 UTC)"
    assert "workflow_dispatch" in on


def test_research_job_has_minimal_write_permission_only_where_needed():
    data = _load()
    research = data["jobs"]["research"]
    assert research["permissions"] == {"contents": "write"}


def test_deploy_pages_job_has_minimal_pages_permissions():
    data = _load()
    deploy = data["jobs"]["deploy-pages"]
    assert deploy["permissions"] == {"contents": "read", "pages": "write", "id-token": "write"}
    assert deploy["needs"] == "research"


def test_top_level_default_permission_is_read_only():
    data = _load()
    assert data["permissions"] == {"contents": "read"}


def test_recovery_run_has_idempotency_check_step():
    data = _load()
    steps = data["jobs"]["research"]["steps"]
    step_names = [s.get("name", "") for s in steps]
    assert any("idempotency" in n.lower() for n in step_names)
    check_step = next(s for s in steps if s.get("id") == "check")
    assert "skip" in check_step["run"]


def test_all_pipeline_steps_use_continue_on_error_so_dashboard_still_deploys():
    data = _load()
    steps = data["jobs"]["research"]["steps"]
    critical_step_ids = {"data-validation", "research-pipeline", "paper-trading", "dashboard-data"}
    found = {s["id"]: s.get("continue-on-error") for s in steps if s.get("id") in critical_step_ids}
    assert found == {sid: True for sid in critical_step_ids}, (
        "every pipeline step must continue-on-error so a data/test failure never blocks the "
        "dashboard commit/deploy (spec: Research failure != Dashboard deploy failure)"
    )


def test_secret_scan_runs_before_the_commit_step():
    data = _load()
    steps = data["jobs"]["research"]["steps"]
    names = [s.get("name", "").lower() for s in steps]
    gitleaks_idx = next(i for i, n in enumerate(names) if "secret scan" in n or "gitleaks" in n)
    commit_idx = next(i for i, n in enumerate(names) if "commit dashboard data" in n)
    assert gitleaks_idx < commit_idx


def test_commit_step_is_gated_on_gitleaks_success():
    data = _load()
    steps = data["jobs"]["research"]["steps"]
    commit_step = next(s for s in steps if "Commit dashboard data" in s.get("name", ""))
    assert "gitleaks.outcome" in commit_step["if"]


def test_deploy_pages_uploads_the_site_directory():
    data = _load()
    steps = data["jobs"]["deploy-pages"]["steps"]
    upload_step = next(s for s in steps if s.get("uses", "").startswith("actions/upload-pages-artifact"))
    assert upload_step["with"]["path"] == "site"


def test_daily_artifacts_uploaded_with_expected_naming():
    data = _load()
    steps = data["jobs"]["research"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert any("daily-validation artifact" in n for n in names)
    assert any("daily-research artifact" in n for n in names)
