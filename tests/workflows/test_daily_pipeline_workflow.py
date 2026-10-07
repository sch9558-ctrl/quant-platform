"""Structural contract for the four-stage private daily pipeline."""
from pathlib import Path
import yaml
P=Path(__file__).resolve().parents[2]/".github/workflows/daily.yml"
def load():
    with open(P,encoding="utf-8") as f:return yaml.safe_load(f)

def test_yaml_parses_and_has_four_ordered_jobs():
    d=load(); assert set(d["jobs"])=={"research","data-quality","dashboard-build","deploy"}
    assert d["jobs"]["data-quality"]["needs"]=="research"
    assert d["jobs"]["dashboard-build"]["needs"]=="data-quality"
    assert d["jobs"]["deploy"]["needs"]=="dashboard-build"

def test_only_latest_closed_session_is_implicit():
    raw=P.read_text(encoding="utf-8")
    assert "--as-of" not in raw
    assert 'cron: "0 22 * * *"' in raw

def test_real_market_data_and_analyst_generation_are_requested():
    raw=P.read_text(encoding="utf-8")
    assert "generate_dashboard_data.py --real" in raw
    assert "generate_consensus_accuracy.py" in raw
    assert "DATA_GO_KR_SERVICE_KEY" in raw

def test_sensitive_job_handoff_is_encrypted():
    raw=P.read_text(encoding="utf-8")
    assert "aes-256-cbc" in raw
    assert "DASHBOARD_ARTIFACT_KEY" in raw
    assert "encrypted-research-" in raw
    assert "encrypted-dashboard-site-" in raw
    assert "git push" not in raw
    assert "git commit" not in raw

def test_frontend_build_precedes_deploy():
    d=load(); steps=d["jobs"]["dashboard-build"]["steps"]
    assert any("npm run build" in s.get("run","") for s in steps)
    dep=d["jobs"]["deploy"]["steps"]
    assert any("wrangler-action" in str(s.get("uses","")) for s in dep)

def test_cloudflare_is_private_and_has_no_public_fallback():
    raw=P.read_text(encoding="utf-8")
    assert "cloudflare_pages.py preflight" in raw
    assert "Cloudflare Access" in raw or "Access management" in raw
    assert "actions/deploy-pages" not in raw
    assert "github.io" not in raw

def test_project_name_secret_has_safe_default():
    raw=P.read_text(encoding="utf-8")
    assert "secrets.CLOUDFLARE_PROJECT_NAME" in raw
    assert "quant-platform" in raw


def test_real_paper_verification_is_persistent_encrypted_and_ordered():
    d=load()
    steps=d["jobs"]["research"]["steps"]
    names=[s.get("name","") for s in steps]
    restore_i=names.index("Restore encrypted long-horizon state cache")
    research_i=names.index("Run real research and dashboard-data generation")
    paper_i=names.index("Run real paper verification for validated markets")
    refresh_i=names.index("Refresh dashboard paper-verification counters")
    encrypt_i=names.index("Encrypt persistent long-horizon state")
    save_i=names.index("Save encrypted long-horizon state cache")
    assert restore_i < research_i < paper_i < refresh_i < encrypt_i < save_i

    raw=P.read_text(encoding="utf-8")
    assert "python run_paper.py --real" in raw
    assert "paper_nav_history" in raw
    assert "paper-state.tgz.enc" in raw
    assert "actions/cache/restore@v4" in raw
    assert "actions/cache/save@v4" in raw
    assert "retention-days: 30" in raw
    assert "data/db" in raw
