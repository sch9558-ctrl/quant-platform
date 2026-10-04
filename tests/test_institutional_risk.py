import pandas as pd

from quant import config

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


def _selected_grid_search_dsrs(
    *,
    annual_sharpe: float,
    seed_start: int,
    repetitions: int | None = None,
):
    import math
    import numpy as np
    from quant.validation.cpcv import annualized_sharpe

    calibration=config.ranking_config()["dsr_calibration"]
    repetitions=int(repetitions or calibration["repetitions"])
    daily_vol=float(calibration["daily_volatility"])
    periods=252
    mean_return=float(annual_sharpe)*daily_vol/math.sqrt(periods)
    n_trials=int(calibration["n_trials"])
    n_obs=int(calibration["observations_per_trial"])

    out=[]
    for seed in range(seed_start, seed_start + repetitions):
        rng=np.random.default_rng(seed)
        trials=rng.normal(mean_return,daily_vol,(n_trials,n_obs))
        sharpes=[annualized_sharpe(x) for x in trials]
        best=int(np.argmax(sharpes))
        out.append(
            deflated_sharpe_ratio(
                trials[best],
                n_trials=n_trials,
                trial_sharpes=sharpes,
            )
        )
    return out


def _wilson_interval(successes: int, n: int, confidence: float) -> tuple[float,float]:
    import math
    from scipy.stats import norm

    alpha=1.0-float(confidence)
    z=float(norm.ppf(1.0-alpha/2.0))
    p=successes/n
    denom=1.0+z*z/n
    center=(p+z*z/(2.0*n))/denom
    half=z*math.sqrt(p*(1.0-p)/n+z*z/(4.0*n*n))/denom
    return center-half,center+half


@pytest.mark.parametrize("seed_start",[1000,50000,90000])
def test_dsr_zero_edge_false_approval_wilson_upper_bound(seed_start):
    import numpy as np

    calibration=config.ranking_config()["dsr_calibration"]
    threshold=float(config.ranking_config()["minimum_requirements"]["min_deflated_sharpe_probability"])
    assert threshold==0.75
    dsrs=np.asarray(
        _selected_grid_search_dsrs(
            annual_sharpe=0.0,
            seed_start=seed_start,
        )
    )
    successes=int(np.sum(dsrs>=threshold))
    _,upper=_wilson_interval(
        successes,
        len(dsrs),
        float(calibration["confidence_level"]),
    )
    assert upper <= float(calibration["max_zero_edge_false_approval_rate"]), (
        f"zero-edge false approval Wilson upper bound {upper:.2%} exceeds "
        f"{float(calibration['max_zero_edge_false_approval_rate']):.2%} "
        f"at threshold {threshold:.2f}, seed_start={seed_start}"
    )


@pytest.mark.parametrize("seed_start",[1000,50000,90000])
def test_dsr_min_detectable_edge_wilson_lower_bound(seed_start):
    import numpy as np

    calibration=config.ranking_config()["dsr_calibration"]
    threshold=float(config.ranking_config()["minimum_requirements"]["min_deflated_sharpe_probability"])
    edge=float(calibration["min_detectable_annual_sharpe"])
    dsrs=np.asarray(
        _selected_grid_search_dsrs(
            annual_sharpe=edge,
            seed_start=seed_start,
        )
    )
    successes=int(np.sum(dsrs>=threshold))
    lower,_=_wilson_interval(
        successes,
        len(dsrs),
        float(calibration["confidence_level"]),
    )
    assert lower >= float(calibration["min_detection_power"]), (
        f"detectable-edge power Wilson lower bound {lower:.2%} is below "
        f"{float(calibration['min_detection_power']):.2%} for annual Sharpe "
        f"{edge:.2f}, threshold {threshold:.2f}, seed_start={seed_start}"
    )


def test_dsr_calibration_contract_is_explicit():
    calibration=config.ranking_config()["dsr_calibration"]
    assert calibration["repetitions"] >= 1000
    assert calibration["min_detectable_annual_sharpe"] == 0.70
    assert calibration["max_zero_edge_false_approval_rate"] == 0.08
    assert calibration["confidence_level"] == 0.95
