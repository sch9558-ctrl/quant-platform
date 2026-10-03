import pandas as pd

from quant.risk_guard import RiskGuard
from quant.validation.cpcv import PurgedCombinatorialCV, calmar_ratio, deflated_sharpe_ratio, max_drawdown_recovery, profit_factor


def test_cpcv_has_no_purge_or_embargo_overlap():
    splitter=PurgedCombinatorialCV(n_groups=6,n_test_groups=2,purge_sessions=2,embargo_sessions=3)
    splits=list(splitter.split(range(60)))
    assert len(splits)==splitter.get_n_splits()==15
    for train,test in splits:
        assert not set(train).intersection(set(test))
        for t in test:
            assert all(abs(int(x)-int(t))>2 for x in train if x <= t)
        assert min(train) >= 0 and max(train) < 60


def test_validation_statistics_are_well_formed():
    r=pd.Series([0.01,-0.005,0.012,-0.004,0.008]*30)
    dsr=deflated_sharpe_ratio(r,n_trials=20)
    dd=max_drawdown_recovery(r)
    assert 0 <= dsr <= 1
    assert dd.max_drawdown <= 0
    assert profit_factor(r)>1
    assert calmar_ratio(r)>0


def test_risk_guard_soft_and_hard_stops_and_var():
    guard=RiskGuard()
    returns=pd.Series([0.003,-0.01,0.005,-0.02,0.004]*20)
    nav_soft=pd.Series([100,101,99,97,95])
    nav_hard=pd.Series([100,102,98,94,91])
    s=guard.evaluate(returns,nav_soft)
    h=guard.evaluate(returns,nav_hard)
    assert s.var95_parametric >= 0 and s.var95_historical >= 0
    assert s.action=="SOFT_STOP"
    assert not s.allow_new_entries and not s.liquidate_all
    assert h.action=="HARD_KILL_SWITCH"
    assert h.liquidate_all


def test_dynamic_position_exit_rules():
    guard=RiskGuard(min_risk_reward=2.5)
    stop=guard.atr_trailing_stop(120,4,multiple=2.5)
    assert stop==110
    assert guard.position_exit_reason(current_price=109,trailing_stop=110,expected_reward=10,expected_risk=3)=="TRAILING_STOP"
    assert guard.position_exit_reason(current_price=115,trailing_stop=110,expected_reward=5,expected_risk=3)=="RISK_REWARD_BELOW_MINIMUM"
    assert guard.position_exit_reason(current_price=115,trailing_stop=110,expected_reward=10,expected_risk=3) is None
