"""Pre-deployment build verification.

These drive the verifier against real files on disk, because that is what
it checks -- the bytes about to be uploaded, not an in-memory object a
test assembled. The important cases are the *contradictions*: a payload
whose headline disagrees with its own metadata is precisely what shipped
2022-06-01 data under a DATA INTEGRITY PASS banner.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "verify_dashboard_build", REPO_ROOT / "tools" / "verify_dashboard_build.py")
vdb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vdb)


def _payload(**overrides) -> dict:
    data = {
        "schema_version": 2,
        "generated_at": "2026-08-26T07:04:00+00:00",
        "as_of": "2026-08-25",
        "data_source_mode": "real",
        "publishability": {
            "data_source_mode": "real",
            "publishable": True,
            "markets": {
                "korea": {"market": "korea", "expected_session": "2026-08-25",
                          "actual_session": "2026-08-25", "gap_sessions": 0, "status": "FRESH"},
            },
            "reasons": [],
        },
        "overview": {
            "data_integrity": "PASS", "mandatory_validation_pass_rate": 100.0,
            "pipeline_health": "PASS", "strategy_validation": "PASS",
            "investment_readiness": "RESEARCH_VALIDATED",
        },
        "markets": {"korea": {"market": "korea", "blocked": False, "candidates": []}},
        "disclaimer": "Data Validation 100% means all mandatory data-quality checks passed.",
    }
    data.update(overrides)
    return data


def _site(tmp_path: Path, payload: dict | None = None, *, history=None,
          index: str | None = None, robots: bool = True) -> Path:
    site = tmp_path / "site"
    (site / "data").mkdir(parents=True)
    (site / "index.html").write_text(
        index if index is not None
        else ('<!doctype html><html lang="ko"><body>' + "x" * 1200
              + '<script>fetch("data/dashboard.json")</script></body></html>'),
        encoding="utf-8")
    (site / "data" / "dashboard.json").write_text(
        json.dumps(payload if payload is not None else _payload(), ensure_ascii=False),
        encoding="utf-8")
    (site / "data" / "history.json").write_text(
        json.dumps(history if history is not None else []), encoding="utf-8")
    if robots:
        (site / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    return site


def _run(site: Path, require_publishable: bool = False) -> vdb.Verifier:
    v = vdb.Verifier(site, require_publishable)
    v.run()
    return v


# ------------------------------------------------------------------
# Happy paths
# ------------------------------------------------------------------
def test_valid_real_fresh_build_passes(tmp_path):
    assert _run(_site(tmp_path)).errors == []


def test_honest_unavailable_state_is_deployable(tmp_path):
    """A dashboard saying "데이터 없음" is a legitimate deployment -- it is
    how the site reports that today's data failed validation. Blocking it
    would leave yesterday's numbers on screen, which is the failure mode
    this whole system exists to avoid."""
    payload = _payload(
        data_source_mode="synthetic",
        publishability={
            "data_source_mode": "synthetic", "publishable": False,
            "markets": {}, "reasons": ["아직 실제 시장 데이터로 생성된 결과가 없습니다."],
        },
        overview={**_payload()["overview"], "data_integrity": "FAIL",
                  "pipeline_health": "FAIL", "strategy_validation": "FAIL",
                  "investment_readiness": "DATA_INVALID"},
    )
    assert _run(_site(tmp_path, payload)).errors == []


# ------------------------------------------------------------------
# The contradictions that shipped the original bug
# ------------------------------------------------------------------
def test_unpublishable_payload_claiming_data_integrity_pass_is_refused(tmp_path):
    """Synthetic/stale data + DATA INTEGRITY PASS -- the exact banner that
    was live. The verifier must refuse it even though every individual
    field is well-formed."""
    payload = _payload(
        data_source_mode="synthetic",
        publishability={
            "data_source_mode": "synthetic", "publishable": False,
            "markets": {}, "reasons": ["합성 데이터입니다."],
        },
        # ...but the headline still says everything is fine
    )
    errors = _run(_site(tmp_path, payload)).errors
    assert any("모순" in e and "데이터 무결성이 PASS" in e for e in errors)


def test_publishable_true_with_synthetic_source_is_refused(tmp_path):
    payload = _payload(data_source_mode="synthetic")  # publishability still says True
    errors = _run(_site(tmp_path, payload)).errors
    assert any("합성 데이터는 게시 가능 상태가 될 수 없습니다" in e for e in errors)


def test_real_current_data_that_failed_its_checks_is_still_deployed(tmp_path):
    """The state this check used to refuse, wrongly.

    `publishable` answers "is this real, current data?"; `data_integrity`
    answers "did it pass the mandatory quality checks?". Real, current data
    that fails a check is not a contradiction -- it is the most important
    thing this dashboard can say, and blocking the deployment would hide it.
    Fail-Closed stops the research, not the reporting of it.

    On 2026-10-01 the first run ever to reach real data for both markets
    landed in exactly this state, and this check refused to publish the page
    that would have explained why.
    """
    payload = _payload(overview={**_payload()["overview"], "data_integrity": "FAIL"})
    result = _run(_site(tmp_path, payload))
    assert result.errors == [], (
        "a validation failure on real, current data must still be publishable "
        f"-- refused with {result.errors}"
    )


def test_unpublishable_without_a_user_facing_reason_is_refused(tmp_path):
    """If we are going to show a failure state, it has to say why."""
    payload = _payload(
        data_source_mode="synthetic",
        publishability={"data_source_mode": "synthetic", "publishable": False,
                        "markets": {}, "reasons": []},
        overview={**_payload()["overview"], "data_integrity": "FAIL"},
    )
    errors = _run(_site(tmp_path, payload)).errors
    assert any("사유가 없습니다" in e for e in errors)


# ------------------------------------------------------------------
# Structure
# ------------------------------------------------------------------
@pytest.mark.parametrize("missing", ["generated_at", "as_of", "data_source_mode",
                                     "publishability", "overview", "disclaimer"])
def test_missing_required_field_is_refused(tmp_path, missing):
    payload = _payload()
    payload.pop(missing)
    errors = _run(_site(tmp_path, payload)).errors
    assert errors, f"removing {missing} should fail verification"


def test_unparseable_json_is_refused(tmp_path):
    site = _site(tmp_path)
    (site / "data" / "dashboard.json").write_text("{ not json", encoding="utf-8")
    errors = _run(site).errors
    assert any("JSON" in e for e in errors)


def test_missing_index_html_is_refused(tmp_path):
    site = _site(tmp_path)
    (site / "index.html").unlink()
    assert any("진입 파일" in e for e in _run(site).errors)


def test_index_not_wired_to_data_is_refused(tmp_path):
    site = _site(tmp_path, index="<!doctype html><html><body>" + "x" * 1200 + "</body></html>")
    assert _run(site).errors


# ------------------------------------------------------------------
# Production / test separation and secrets
# ------------------------------------------------------------------
@pytest.mark.parametrize("leaked", ["tests/conftest.py", "fixtures/sample.json",
                                    "demo/data.json", "data/__pycache__/x.json"])
def test_test_artifacts_in_the_deploy_directory_are_refused(tmp_path, leaked):
    site = _site(tmp_path)
    target = site / leaked
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{}", encoding="utf-8")
    assert any("테스트/샘플 산출물" in e for e in _run(site).errors)


@pytest.mark.parametrize("secret", [
    "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
    "AKIAIOSFODNN7EXAMPLE",
    'api_key = "s3cr3tvalue123456"',
    "-----BEGIN RSA PRIVATE KEY-----",
])
def test_secret_shaped_content_in_the_artifact_is_refused(tmp_path, secret):
    site = _site(tmp_path)
    (site / "leaked.js").write_text(f"const x = '{secret}';", encoding="utf-8")
    assert any("비밀정보로 보이는 값" in e for e in _run(site).errors)


def test_data_version_hashes_do_not_trip_the_secret_scan(tmp_path):
    """Payloads are full of hashes and data-version fingerprints. A scanner
    that flags those gets ignored, which is worse than no scanner."""
    payload = _payload()
    payload["provenance"] = {
        "korea": {"data_version": "a3f5c8e1b2d4906f7e8a1c3b5d7f9e0a1c3b5d7f9e0a1c3b5d7f9e0a1c3b5d7f",
                  "checksum": "9e0a1c3b5d7f9e0a1c3b5d7f9e0a1c3b5d7f9e0a"}
    }
    assert _run(_site(tmp_path, payload)).errors == []


def test_missing_robots_is_a_warning_not_a_failure(tmp_path):
    """noindex is a courtesy to crawlers, not access control -- it must not
    be able to block a deployment, and must not be mistaken for security."""
    v = _run(_site(tmp_path, robots=False))
    assert v.errors == []
    assert any("robots.txt" in w for w in v.warnings)


def test_require_publishable_blocks_the_unavailable_state(tmp_path):
    payload = _payload(
        data_source_mode="synthetic",
        publishability={"data_source_mode": "synthetic", "publishable": False,
                        "markets": {}, "reasons": ["합성 데이터입니다."]},
        overview={**_payload()["overview"], "data_integrity": "FAIL"},
    )
    v = _run(_site(tmp_path, payload), require_publishable=True)
    assert any("--require-publishable" in e for e in v.errors)


def test_repository_does_not_commit_private_daily_json():
    """Production research data is created in CI, encrypted between jobs, and not committed."""
    assert not (REPO_ROOT / "site" / "data" / "dashboard.json").exists()
    assert not (REPO_ROOT / "site" / "data" / "history.json").exists()


def test_vite_built_entry_point_is_accepted(tmp_path):
    site=tmp_path/"site"; data=site/"data"; data.mkdir(parents=True)
    (site/"index.html").write_text('<html><script type="module" src="./assets/index-abc.js"></script></html>' + "x"*1200)
    (site/"robots.txt").write_text("User-agent: *\nDisallow: /\n")
    payload={
      "schema_version":2,"generated_at":"2026-10-03T00:00:00Z","as_of":"2026-10-02",
      "data_source_mode":"real","publishability":{"publishable":True,"markets":{},"reasons":[]},
      "overview":{"data_integrity":"FAIL","mandatory_validation_pass_rate":0,"pipeline_health":"FAIL","strategy_validation":"FAIL","investment_readiness":"DATA_INVALID"},
      "markets":{},"disclaimer":"research only"
    }
    import json
    (data/"dashboard.json").write_text(json.dumps(payload))
    (data/"history.json").write_text("[]")
    from tools.verify_dashboard_build import Verifier
    assert Verifier(site,False).run()==0


def test_delayed_acceptable_freshness_is_valid(tmp_path):
    payload = _payload(
        publishability={
            "data_source_mode": "real",
            "publishable": True,
            "markets": {
                "korea": {
                    "market": "korea",
                    "expected_session": "2026-10-02",
                    "actual_session": "2026-10-01",
                    "gap_sessions": 1,
                    "status": "DELAYED_ACCEPTABLE",
                },
            },
            "reasons": ["국내시장 공급자 게시 지연 1거래일"],
        }
    )
    assert _run(_site(tmp_path, payload)).errors == []
