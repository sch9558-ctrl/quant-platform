import pandas as pd
from quant.validation import purged_embargo_splits, max_drawdown_and_recovery, profit_factor, deflated_sharpe_ratio
from quant.risk_guard import RiskGuard

def test_purged_embargo_split_excludes_nearby_rows():
    for train,test in purged_embargo_splits(100,5,purge=3,embargo=5):
        assert not any((train>=test[0]-3)&(train<=test[-1]+5))

def test_statistics_and_drawdown_guard():
    r=pd.Series([.01,-.02,.03,-.01,.02]*30)
    mdd,recovery=max_drawdown_and_recovery(r)
    assert mdd<=0
    assert profit_factor(r)>0
    assert 0<=deflated_sharpe_ratio(r,3)<=1
    state=RiskGuard().evaluate_drawdown(pd.Series([100,102,101,95,93]))
    assert not state.allow_new_entries
