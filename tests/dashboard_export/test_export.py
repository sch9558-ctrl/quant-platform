import json

import pandas as pd
import pytest

from quant.dashboard_export.export import (
    FORBIDDEN_PHRASES, _assert_no_forbidden_phrases, _market_section, _strategy_rows,
    _strategy_validation_status, append_history, build_dashboard_data, write_dashboard_json,
)
from quant.pipeline import research_pipeline
from quant.quality.system_status import compute_system_status
from quant.research_db.db import ResearchDB
from quant.strategy import registry


@pytest.fixture(scope="module")
def dashboard_data():
    # Built once per module (expensive: runs a real walk-forward pass) --
    # tmp_path isolation happens per-call inside run_market_research via
    # quant.config.resolve_path, which module-scoped fixtures can't
    # monkeypatch, so this fixture patches it directly for its own scope.
    # build_dashboard_data() itself must run INSIDE this patched block too
    # (not in the test body afterward) -- it reads the audit log via the
    # same quant.config.resolve_path, which would otherwise point back at
    # the real project db_dir once this fixture's finally: block restores it.
    from quant import config as quant_config
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp())
    original_resolve_path = quant_config.resolve_path
    original_research_db = research_pipeline.ResearchDB
    quant_config.resolve_path = lambda rel: tmp
    # run_full_pipeline() constructs a bare ResearchDB() internally, which
    # resolves a *file* path via config.resolve_path(full_path_str) -- the
    # blanket `lambda rel: tmp` above would hand it a bare directory
    # instead of a file path, so (mirroring
    # tests/pipeline/test_research_pipeline.py::test_run_full_pipeline_writes_report)
    # patch the ResearchDB construction directly too.
    research_pipeline.ResearchDB = lambda: ResearchDB(path=tmp / "research.sqlite")
    import quant.strategy.registry as real_registry
    orig_ids = real_registry.enabled_strategy_ids
    real_registry.enabled_strategy_ids = lambda: ["ma_crossover", "rsi_reversal"]
    try:
        pipeline_result = research_pipeline.run_full_pipeline(
            demo=True, as_of="2022-06-01", top_n=5, use_param_search=False, markets=("korea",),
        )
        status = compute_system_status(["korea"], demo=True, as_of="2022-06-01", run_tests=False)
        data = build_dashboard_data(pipeline_result, status, demo=True)
    finally:
        real_registry.enabled_strategy_ids = orig_ids
        quant_config.resolve_path = original_resolve_path
        research_pipeline.ResearchDB = original_research_db
    return data


def test_build_dashboard_data_end_to_end(dashboard_data):
    data = dashboard_data

    assert data["as_of"] == "2022-06-01"
    assert data["overview"]["data_integrity"] == "PASS"
    assert data["overview"]["mandatory_validation_pass_rate"] == 100.0
    assert data["overview"]["investment_readiness"] in {
        "DATA_INVALID", "DATA_VERIFIED", "RESEARCH_VALIDATED", "OOS_VALIDATED",
        "PAPER_TRADING", "PAPER_VERIFIED", "ELIGIBLE_FOR_MANUAL_REVIEW",
    }
    assert "Data Validation 100%" in data["disclaimer"]

    kr = data["markets"]["korea"]
    assert kr["blocked"] is False
    assert kr["universe_size"] > 0
    assert len(kr["candidates"]) <= 5
    if kr["candidates"]:
        c = kr["candidates"][0]
        assert c["rank"] == 1
        assert set(["symbol", "company", "market", "price", "momentum", "trend",
                     "relative_strength", "volume", "volatility", "fundamental_score",
                     "strategy_signal", "risk_score", "composite_score"]).issubset(c)

    strategies = data["strategies"]["korea"]
    assert {r["strategy_id"] for r in strategies} == {"ma_crossover", "rsi_reversal"}
    for row in strategies:
        assert "aggregate_oos_sharpe" in row and "aggregate_oos_cagr" in row

    backtests = data["backtests"]["korea"]
    assert {b["strategy_id"] for b in backtests} == {"ma_crossover", "rsi_reversal"}
    for b in backtests:
        assert b["n_folds"] == len(b["folds"])

    assert "korea" in data["paper_trading"]
    assert "us" in data["paper_trading"]
    assert data["provenance"]["korea"]["validation_status"] == "PASS"
    assert data["provenance"]["korea"]["data_version"] is not None

    assert data["validation"]["investment_readiness"]["level"] == data["overview"]["investment_readiness"]
    assert "100%" in data["validation"]["investment_readiness"]["disclaimer"]
    assert data["validation"]["markets"]["korea"]["overall_status"] == "PASS"
    assert isinstance(data["audit_log"], list)
    assert len(data["audit_log"]) > 0
    assert {"check", "result", "market"}.issubset(data["audit_log"][0])


def test_blocked_market_renders_fail_not_stale_candidates():
    fake_blocked = research_pipeline.MarketResearchResult(
        market="korea", scan=None, walk_forward_results={}, ranking_df=pd.DataFrame(),
        experiment_ids=[], new_strategy_ids=[], updated_strategy_ids=[],
        portfolio_allocation=None, risk_checks=[],
        quality_report=None, blocked=True, block_reason="DATA VALIDATION FAILED for market=korea: mandatory check(s) failed.",
    )
    section = _market_section("korea", fake_blocked)
    assert section["status"] == "DATA VALIDATION FAILED"
    assert section["blocked"] is True
    assert section["candidates"] == []
    assert "DATA VALIDATION FAILED" in section["block_reason"]
    assert _strategy_validation_status(fake_blocked) == "FAIL"
    assert _strategy_rows(fake_blocked) == []


def test_strategy_validation_status_warning_when_ranking_empty():
    fake_ok_but_empty = research_pipeline.MarketResearchResult(
        market="korea", scan=None, walk_forward_results={}, ranking_df=pd.DataFrame(),
        experiment_ids=[], new_strategy_ids=[], updated_strategy_ids=[],
        portfolio_allocation=None, risk_checks=[], blocked=False, block_reason=None,
    )
    assert _strategy_validation_status(fake_ok_but_empty) == "WARNING"


def test_forbidden_phrase_detection_raises():
    with pytest.raises(ValueError, match="forbidden phrase"):
        _assert_no_forbidden_phrases({"note": f"this strategy has {FORBIDDEN_PHRASES[0]}"})


def test_write_dashboard_json_and_append_history_idempotent(tmp_path, dashboard_data):
    data = dashboard_data

    path = write_dashboard_json(data, tmp_path)
    assert path.exists()
    loaded = json.loads(path.read_text())
    assert loaded["as_of"] == "2022-06-01"

    hist_path = append_history(data, tmp_path)
    hist_path = append_history(data, tmp_path)  # run twice for the same as_of
    rows = json.loads(hist_path.read_text())
    assert sum(1 for r in rows if r["as_of"] == "2022-06-01") == 1  # replaced, not duplicated
