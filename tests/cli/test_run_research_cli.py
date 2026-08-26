"""Regression test for run_research.py's CLI print loop (spec section 2:
Fail-Closed must degrade gracefully, never crash the daily driver script).

Bug this guards against: run_market_research() can return a
MarketResearchResult with blocked=True and scan=None/portfolio_allocation=None
(added when the Fail-Closed gate was wired into the research pipeline).
run_research.py's report-printing loop originally accessed
`mr.scan.universe_size` / `mr.portfolio_allocation.weights` unconditionally,
which would raise AttributeError on a blocked market -- turning a "data
validation failed today, skip candidates" situation into a hard crash of
the one-command daily driver, which is worse than the failure it was
supposed to handle safely.
"""
import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_run_research_module():
    spec = importlib.util.spec_from_file_location("run_research_cli_under_test", REPO_ROOT / "run_research.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def run_research_module():
    return _load_run_research_module()


def _blocked_result(market: str):
    from quant.pipeline.research_pipeline import MarketResearchResult
    return MarketResearchResult(
        market=market, scan=None, walk_forward_results={}, ranking_df=pd.DataFrame(),
        experiment_ids=[], new_strategy_ids=[], updated_strategy_ids=[],
        portfolio_allocation=None, risk_checks=[],
        quality_report=None, blocked=True,
        block_reason=f"DATA VALIDATION FAILED for market={market}: mandatory check(s) failed.",
    )


def test_main_does_not_crash_when_a_market_is_blocked(run_research_module, monkeypatch, tmp_path, capsys):
    from quant.pipeline.research_pipeline import ResearchPipelineResult

    fake_result = ResearchPipelineResult(
        as_of="2022-06-01",
        markets={"korea": _blocked_result("korea")},
        report_text="# Daily Research Report",
        report_path=str(tmp_path / "report.md"),
    )
    monkeypatch.setattr(run_research_module, "run_full_pipeline", lambda **kwargs: fake_result)
    monkeypatch.setattr(sys, "argv", ["run_research.py", "--markets", "korea", "--as-of", "2022-06-01"])

    exit_code = run_research_module.main()

    captured = capsys.readouterr()
    assert "DATA VALIDATION: FAIL" in captured.out
    assert "오늘의 투자 후보 생성 중단" in captured.out
    assert exit_code == 1  # a blocked market is reported via exit code, not silently swallowed


def test_main_returns_zero_when_all_markets_pass(run_research_module, monkeypatch, tmp_path, capsys):
    from quant.pipeline.research_pipeline import MarketResearchResult, ResearchPipelineResult
    from quant.portfolio.constructor import PortfolioAllocation
    from quant.scanner.scanner import ScanResult

    ok_scan = ScanResult(
        market="korea", as_of=pd.Timestamp("2022-06-01"), regime=None,
        universe_size=10, top_candidates=[], all_candidates=[], excluded_for_quality=[],
    )
    ok_result = MarketResearchResult(
        market="korea", scan=ok_scan, walk_forward_results={}, ranking_df=pd.DataFrame(),
        experiment_ids=[], new_strategy_ids=[], updated_strategy_ids=[],
        portfolio_allocation=PortfolioAllocation(
            weights=pd.Series(dtype=float), cash_weight=1.0, by_market={}, by_strategy={}, by_sector={},
        ),
        risk_checks=[], blocked=False, block_reason=None,
    )
    fake_result = ResearchPipelineResult(
        as_of="2022-06-01", markets={"korea": ok_result},
        report_text="# Daily Research Report", report_path=str(tmp_path / "report.md"),
    )
    monkeypatch.setattr(run_research_module, "run_full_pipeline", lambda **kwargs: fake_result)
    monkeypatch.setattr(sys, "argv", ["run_research.py", "--markets", "korea", "--as-of", "2022-06-01"])

    exit_code = run_research_module.main()
    assert exit_code == 0
    assert "DATA VALIDATION: FAIL" not in capsys.readouterr().out
