"""One market's outage must not take the other market's run with it.

On 2026-09-30 KRX did not answer GitHub's runners at all. `list_symbols`
raised inside the Korean leg, before the Fail-Closed gate had a quality
report to judge, and the exception propagated straight out of
`run_full_pipeline` -- discarding a US run that had worked.

That is the wrong shape. "No trustworthy data for this market today" is
exactly what the Fail-Closed gate already expresses, and a provider being
unreachable is one more way to arrive there. So a market that raises is
recorded as blocked, with a reason naming the cause, and every other
market still runs.

The failure mode this guards against is not a crash the user would see --
it is a *quiet* loss: the dashboard simply has no US section, and nothing
says why.
"""
from __future__ import annotations

import pandas as pd
import pytest

from quant.pipeline import research_pipeline
from quant.pipeline.research_pipeline import MarketResearchResult, run_full_pipeline


def _ok(market: str) -> MarketResearchResult:
    return MarketResearchResult(
        market=market, scan=None, walk_forward_results={}, ranking_df=pd.DataFrame(),
        experiment_ids=[], new_strategy_ids=[], updated_strategy_ids=[],
        portfolio_allocation=None, risk_checks=[], quality_report=None,
        blocked=False, block_reason=None, as_of="2026-09-29",
    )


@pytest.fixture
def one_market_down(monkeypatch):
    """Korea raises the way an unreachable KRX raises; the US leg works."""
    calls = []

    def fake_run_market_research(market, **kwargs):
        calls.append(market)
        if market == "korea":
            raise ConnectionError("Expecting value: line 1 column 1 (char 0)")
        return _ok(market)

    monkeypatch.setattr(research_pipeline, "run_market_research", fake_run_market_research)
    monkeypatch.setattr(research_pipeline, "ResearchDB", lambda *a, **k: object())
    monkeypatch.setattr(research_pipeline, "generate_daily_report", lambda **k: "report")
    monkeypatch.setattr(research_pipeline, "save_report", lambda *a, **k: "reports/x.md")
    return calls


def test_a_dead_market_does_not_abort_the_other_one(one_market_down):
    result = run_full_pipeline(demo=True, markets=("korea", "us"))
    assert one_market_down == ["korea", "us"], (
        "the US leg never ran -- an exception in the first market ended the "
        "whole pipeline, which is how a completed US run got discarded"
    )
    assert result.markets["us"].blocked is False


def test_the_dead_market_is_reported_as_blocked_not_missing(one_market_down):
    """Absent and blocked look identical on a dashboard unless one of them
    carries a reason. Silence is the failure being described here."""
    result = run_full_pipeline(demo=True, markets=("korea", "us"))
    kr = result.markets["korea"]
    assert kr is not None, "the market must appear in the result at all"
    assert kr.blocked is True
    assert kr.block_reason, "a blocked market with no reason explains nothing"


def test_the_reason_names_the_cause_rather_than_a_traceback(one_market_down):
    result = run_full_pipeline(demo=True, markets=("korea", "us"))
    reason = result.markets["korea"].block_reason
    assert "ConnectionError" in reason, "the exception type should survive into the reason"
    assert "korea" in reason
    assert "Traceback" not in reason


def test_no_candidates_survive_a_blocked_market(one_market_down):
    """Fail-Closed is the whole point: a market with no trustworthy data
    produces no candidates, no strategy evaluation, no allocation."""
    result = run_full_pipeline(demo=True, markets=("korea", "us"))
    kr = result.markets["korea"]
    assert kr.scan is None
    assert kr.walk_forward_results == {}
    assert kr.ranking_df.empty
    assert kr.portfolio_allocation is None
    assert kr.experiment_ids == []


def test_every_market_failing_still_returns_a_result(monkeypatch):
    """A total outage should still produce a renderable, honest run rather
    than an exception -- the dashboard must be able to say so."""
    monkeypatch.setattr(
        research_pipeline, "run_market_research",
        lambda market, **k: (_ for _ in ()).throw(ConnectionError("down")),
    )
    monkeypatch.setattr(research_pipeline, "ResearchDB", lambda *a, **k: object())
    monkeypatch.setattr(research_pipeline, "generate_daily_report", lambda **k: "report")
    monkeypatch.setattr(research_pipeline, "save_report", lambda *a, **k: "reports/x.md")

    result = run_full_pipeline(demo=True, markets=("korea", "us"))
    assert set(result.markets) == {"korea", "us"}
    assert all(m.blocked for m in result.markets.values())


def test_korea_total_outage_still_produces_honest_dashboard_state(one_market_down):
    from quant.dashboard_export.export import _market_section

    result = run_full_pipeline(demo=True, markets=("korea", "us"))
    kr_section = _market_section("korea", result.markets["korea"])

    assert result.markets["us"].blocked is False
    assert kr_section["blocked"] is True
    assert kr_section["status"] == "DATA VALIDATION FAILED"
    assert kr_section["candidates"] == []
    assert kr_section["block_reason"]
