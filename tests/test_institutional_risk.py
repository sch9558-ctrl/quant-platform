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
    assert dsr == 0.0, "multi-trial DSR without cross-trial dispersion must fail closed"
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
    assert guard.entry_risk_reward_allowed(expected_reward=5,expected_risk=3) is False
    assert guard.entry_risk_reward_allowed(expected_reward=10,expected_risk=3) is True
    # Remaining R/R may shrink near a target without forcing a winning trade out.
    assert guard.position_exit_reason(current_price=115,trailing_stop=110,expected_reward=5,expected_risk=3) is None


def test_dsr_uses_observed_trial_sharpe_dispersion():
    import numpy as np
    from quant.validation.cpcv import annualized_sharpe

    rng=np.random.default_rng(23)
    trials=rng.normal(0,0.01,(51,252))
    sharpes=[annualized_sharpe(x) for x in trials]
    best=int(np.argmax(sharpes))
    observed=deflated_sharpe_ratio(trials[best],n_trials=51,trial_sharpes=sharpes)
    center=float(np.mean(sharpes))
    narrow=[center+(x-center)*0.25 for x in sharpes]
    wide=[center+(x-center)*1.50 for x in sharpes]
    narrow_dsr=deflated_sharpe_ratio(trials[best],n_trials=51,trial_sharpes=narrow)
    wide_dsr=deflated_sharpe_ratio(trials[best],n_trials=51,trial_sharpes=wide)
    assert 0 <= observed <= 1
    assert wide_dsr < observed < narrow_dsr
    assert observed < 0.5


def test_multitrial_dsr_requires_trial_dispersion():
    import numpy as np
    rng=np.random.default_rng(7)
    returns=rng.normal(0,0.01,504)
    assert deflated_sharpe_ratio(returns,n_trials=51)==0.0


def test_zero_edge_grid_search_dsr_median_is_below_half():
    import numpy as np
    from quant.validation.cpcv import annualized_sharpe

    dsrs=[]
    for seed in range(50):
        rng=np.random.default_rng(seed)
        trials=rng.normal(0,0.01,(51,504))
        sharpes=[annualized_sharpe(x) for x in trials]
        best=int(np.argmax(sharpes))
        dsrs.append(
            deflated_sharpe_ratio(
                trials[best],
                n_trials=51,
                trial_sharpes=sharpes,
            )
        )
    assert float(np.median(dsrs)) < 0.5


def _selected_grid_search_dsrs(*, mean_return: float, seed_start: int, repetitions: int = 80):
    import numpy as np
    from quant.validation.cpcv import annualized_sharpe

    out=[]
    for seed in range(seed_start, seed_start + repetitions):
        rng=np.random.default_rng(seed)
        trials=rng.normal(mean_return,0.01,(51,504))
        sharpes=[annualized_sharpe(x) for x in trials]
        best=int(np.argmax(sharpes))
        out.append(
            deflated_sharpe_ratio(
                trials[best],
                n_trials=51,
                trial_sharpes=sharpes,
            )
        )
    return out


def test_dsr_false_approval_rate_is_below_ten_percent():
    import numpy as np

    threshold=0.70
    dsrs=_selected_grid_search_dsrs(mean_return=0.0,seed_start=1000,repetitions=80)
    false_approval_rate=float(np.mean(np.asarray(dsrs)>=threshold))
    assert false_approval_rate <= 0.10, (
        f"zero-edge false approval rate {false_approval_rate:.1%} exceeds 10% "
        f"at DSR threshold {threshold:.2f}"
    )
    assert float(np.median(dsrs)) < 0.5


def test_dsr_keeps_high_power_for_a_predeclared_positive_edge():
    import numpy as np

    # Predeclared alternative: daily mean +5bp, daily sigma 1%,
    # annualized population Sharpe ~= 0.79, with the same 51-trial selection.
    threshold=0.70
    dsrs=_selected_grid_search_dsrs(mean_return=0.0005,seed_start=2000,repetitions=80)
    approval_rate=float(np.mean(np.asarray(dsrs)>=threshold))
    assert approval_rate >= 0.90, (
        f"positive-edge approval rate {approval_rate:.1%} is below 90% "
        f"at DSR threshold {threshold:.2f}"
    )
