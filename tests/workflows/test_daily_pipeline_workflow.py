"""Structural guardrails for .github/workflows/daily.yml (spec
sections 24-28). Not a GitHub Actions runner test -- these check the YAML
shape so a future edit can't silently break the schedule, the
idempotency guard, or the minimal-permissions requirement without a test
failing.
"""
from pathlib import Path

import yaml

WORKFLOW_PATH = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "daily.yml"


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


def test_deploy_job_needs_no_pages_permissions():
    """The dashboard is deployed to an external private host, so the
    workflow should not be holding GitHub Pages write or id-token
    permissions it no longer needs."""
    data = _load()
    deploy = data["jobs"]["deploy"]
    assert deploy["permissions"] == {"contents": "read"}
    assert deploy["needs"] == "research"
    assert "pages" not in deploy["permissions"]
    assert "id-token" not in deploy["permissions"]


def test_no_public_github_pages_deployment_remains():
    """Guards the private-hosting migration: a re-added public Pages deploy
    would silently republish the research data to an unauthenticated URL."""
    raw = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "actions/deploy-pages" not in raw
    assert "actions/upload-pages-artifact" not in raw
    assert "actions/configure-pages" not in raw
    assert "deploy-pages:" not in raw


def test_deploy_fails_closed_when_credentials_are_missing():
    """An authentication problem must never be resolved by publishing the
    dashboard somewhere public (spec section 122)."""
    data = _load()
    steps = data["jobs"]["deploy"]["steps"]
    guard = next(s for s in steps if "credentials" in s.get("name", "").lower())
    assert "exit 1" in guard["run"]
    assert "CLOUDFLARE_API_TOKEN" in guard["run"]
    assert "CLOUDFLARE_ACCOUNT_ID" in guard["run"]


def test_build_is_verified_before_deployment():
    data = _load()
    steps = data["jobs"]["deploy"]["steps"]
    names = [s.get("name", "") for s in steps]
    verify_idx = next(i for i, n in enumerate(names) if "Verify dashboard build" in n)
    deploy_idx = next(i for i, s in enumerate(steps)
                      if "wrangler-action" in str(s.get("uses", "")))
    assert verify_idx < deploy_idx, "the build must be verified before it is uploaded"
    assert "verify_dashboard_build.py" in steps[verify_idx]["run"]


def test_secrets_are_read_from_github_secrets_not_inlined():
    raw = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "secrets.CLOUDFLARE_API_TOKEN" in raw
    assert "secrets.CLOUDFLARE_ACCOUNT_ID" in raw
    # no literal token-shaped value anywhere in the workflow
    import re
    assert not re.search(r"[A-Za-z0-9_\-]{40,}", raw.replace("${{ secrets.CLOUDFLARE_API_TOKEN }}", "")
                         .replace("${{ secrets.CLOUDFLARE_ACCOUNT_ID }}", "")), \
        "workflow contains a long literal that may be an inlined credential"


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
    # `dashboard-data` runs the full research pipeline itself (and writes
    # reports/*.md), so there is deliberately no separate research step --
    # duplicating it would repeat every provider fetch and every Walk-Forward
    # evaluation against live data for the same day.
    critical_step_ids = {"data-validation", "paper-trading", "dashboard-data"}
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


def test_deploy_uploads_the_site_directory():
    data = _load()
    steps = data["jobs"]["deploy"]["steps"]
    deploy_step = next(s for s in steps if "wrangler-action" in str(s.get("uses", "")))
    assert "pages deploy site" in deploy_step["with"]["command"]


def test_daily_artifacts_uploaded_with_expected_naming():
    data = _load()
    steps = data["jobs"]["research"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert any("daily-validation artifact" in n for n in names)
    assert any("daily-research artifact" in n for n in names)


def test_pipeline_steps_request_real_market_data():
    """Every data-touching step must pass --real.

    Without it the scripts default to the synthetic offline dataset, which
    is exactly the failure this project shipped with: the daily run produced
    a dashboard of randomly-generated prices that was indistinguishable, from
    the outside, from a real one.
    """
    data = _load()
    steps = data["jobs"]["research"]["steps"]
    for step_id in ("data-validation", "paper-trading", "dashboard-data"):
        step = next(s for s in steps if s.get("id") == step_id)
        assert "--real" in step["run"], f"{step_id} would silently run on synthetic data"


def test_research_job_has_a_wall_clock_timeout():
    """Live providers can hang; a run must fail late rather than never."""
    data = _load()
    timeout = data["jobs"]["research"].get("timeout-minutes")
    assert isinstance(timeout, int) and 0 < timeout <= 360
