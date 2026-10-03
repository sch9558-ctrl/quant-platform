"""Guardrails for standalone private Cloudflare dashboard deployment."""
from pathlib import Path
import yaml

PATH = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy-dashboard.yml"

def _load():
    with open(PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)

def test_secret_fallbacks_are_present():
    raw = PATH.read_text(encoding="utf-8")
    assert "secrets.CLOUDFLARE_API_TOKEN" in raw
    assert "secrets.CF_API_TOKEN" in raw
    assert "secrets.CLOUDFLARE_ACCESS_API_TOKEN" in raw
    assert "secrets.CF_ACCESS_API_TOKEN" in raw
    assert "secrets.CLOUDFLARE_ACCOUNT_ID" in raw
    assert "secrets.CF_ACCOUNT_ID" in raw

def test_site_is_prepared_before_bootstrap_and_publish():
    data = _load()
    steps = data["jobs"]["deploy"]["steps"]
    prep = next(s for s in steps if s.get("name") == "Prepare Site Directory")
    assert "mkdir -p site" in prep["run"]
    assert "reports/dashboard.html" in prep["run"]
    assert "site/index.html" in prep["run"]
    prep_i = steps.index(prep)
    bootstrap_i = next(i for i,s in enumerate(steps) if "Bootstrap Pages project" in s.get("name",""))
    publish_i = next(i for i,s in enumerate(steps) if "wrangler-action" in str(s.get("uses","")))
    assert prep_i < bootstrap_i < publish_i

def test_wrangler_deploy_is_noninteractive_and_targets_site():
    data = _load()
    publish = next(s for s in data["jobs"]["deploy"]["steps"] if "wrangler-action" in str(s.get("uses","")))
    cmd = publish["with"]["command"]
    assert "pages deploy site" in cmd
    assert "--project-name=quant-platform" in cmd
    assert "--branch=master" in cmd
    assert "--commit-dirty=true" in cmd

def test_public_github_pages_fallback_is_absent():
    raw = PATH.read_text(encoding="utf-8")
    assert "actions/deploy-pages" not in raw
    assert "github.io" not in raw


def test_access_preflight_safely_gates_private_publish():
    data = _load()
    steps = data["jobs"]["deploy"]["steps"]
    preflight = next(s for s in steps if s.get("id") == "cf-preflight")
    assert "cloudflare_pages.py preflight" in preflight["run"]
    assert '"ready=false"' in preflight["run"]
    publish = next(s for s in steps if "wrangler-action" in str(s.get("uses", "")))
    verify = next(s for s in steps if "Verify root URL is protected" in s.get("name", ""))
    assert "cf-preflight.outputs.ready == 'true'" in publish["if"]
    assert "cf-preflight.outputs.ready == 'true'" in verify["if"]
    skip = next(s for s in steps if s.get("name") == "Record safe deployment skip")
    assert "CLOUDFLARE_ACCESS_API_TOKEN" in skip["run"]
