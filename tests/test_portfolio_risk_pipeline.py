import pandas as pd
import pytest

from quant.pipeline.research_pipeline import (
    _apply_portfolio_risk_to_scan,
    _portfolio_risk_analysis,
)
from quant.portfolio.constructor import PortfolioAllocation
from quant.risk_guard import RiskGuard


class _Scan:
    def __init__(self):
        self.top_candidates=["A","B"]


def test_risk_guard_exact_soft_and_hard_boundaries():
    guard=RiskGuard()
    assert guard.drawdown_action(pd.Series([100.0,95.0]))==("SOFT_STOP",False,False)
    assert guard.drawdown_action(pd.Series([100.0,92.0]))==("HARD_KILL_SWITCH",False,True)


def test_risk_guard_var_matches_known_values():
    guard=RiskGuard()
    returns=pd.Series([-0.04,-0.02,0.0,0.01,0.02])
    pvar,hvar=guard.value_at_risk(returns)
    assert pvar==pytest.approx(0.0456133210344114,abs=1e-12)
    assert hvar==pytest.approx(0.036,abs=1e-12)


def test_portfolio_risk_missing_nav_is_insufficient_evidence():
    idx=pd.bdate_range("2026-01-01",periods=80)
    close=pd.Series(range(100,180),index=idx,dtype=float)
    ohlcv={"A":pd.DataFrame({"close":close})}
    allocation=PortfolioAllocation(
        weights=pd.Series({"A":.10}),cash_weight=.90,
        by_market={"korea":.10},by_strategy={"scanner":.10},by_sector={},notes=[]
    )
    state=_portfolio_risk_analysis("korea",allocation,ohlcv,nav=pd.Series(dtype=float))
    assert state["state"]=="INSUFFICIENT_EVIDENCE"
    assert state["allow_new_entries"] is False
    assert state["liquidate_all"] is False
    assert any("운용 NAV 관측치 부족" in r for r in state["reasons"])


def test_hard_kill_switch_empties_candidate_list():
    scan=_Scan()
    _apply_portfolio_risk_to_scan(scan,{"liquidate_all":True,"state":"HARD_KILL_SWITCH"})
    assert scan.top_candidates==[]


def test_non_kill_risk_state_keeps_research_candidates():
    scan=_Scan()
    _apply_portfolio_risk_to_scan(scan,{"liquidate_all":False,"state":"SOFT_STOP"})
    assert scan.top_candidates==["A","B"]
