import pandas as pd

from quant.ranking.overfitting import (
    assess_overfitting,
    probability_of_backtest_overfitting_proxy,
)
from quant.validation.cpcv import deflated_sharpe_ratio


def test_assess_overfitting_flags_large_gap_and_few_trades_as_high_risk():
    result = assess_overfitting("strat_a", is_sharpe=2.5, oos_sharpe=0.1, n_trades=5, n_param_combos_tested=50)
    assert result.risk_level == "high"
    assert len(result.reasons) >= 2


def test_assess_overfitting_low_risk_when_consistent_and_well_sampled():
    result = assess_overfitting("strat_b", is_sharpe=1.0, oos_sharpe=0.9, n_trades=200, n_param_combos_tested=5)
    assert result.risk_level == "low"
    assert result.reasons == []


def test_deflated_sharpe_ratio_decreases_with_more_trials():
    returns=pd.Series([0.002,-0.001,0.001,-0.002,0.001,0.0]*60)
    trial_sharpes=[0.4,1.2,0.8,0.1]
    dsr_few=deflated_sharpe_ratio(
        returns,n_trials=4,trial_sharpes=trial_sharpes
    )
    dsr_many=deflated_sharpe_ratio(
        returns,n_trials=500,trial_sharpes=trial_sharpes
    )
    assert dsr_many < dsr_few


def test_deflated_sharpe_ratio_requires_dispersion_for_multiple_trials():
    returns=pd.Series([0.01,-0.005,0.008,-0.004,0.009]*80)
    assert deflated_sharpe_ratio(returns,n_trials=100)==0.0


def test_probability_of_backtest_overfitting_proxy():
    assert probability_of_backtest_overfitting_proxy([]) == 0.0
    assert probability_of_backtest_overfitting_proxy([1.0, 1.5, 2.0]) == 0.0
    assert probability_of_backtest_overfitting_proxy([-1.0, -0.5, 1.0, 2.0]) == 0.5
