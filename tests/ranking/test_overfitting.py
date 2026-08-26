from quant.ranking.overfitting import (
    assess_overfitting,
    deflated_sharpe_ratio,
    probability_of_backtest_overfitting_proxy,
)


def test_assess_overfitting_flags_large_gap_and_few_trades_as_high_risk():
    result = assess_overfitting("strat_a", is_sharpe=2.5, oos_sharpe=0.1, n_trades=5, n_param_combos_tested=50)
    assert result.risk_level == "high"
    assert len(result.reasons) >= 2


def test_assess_overfitting_low_risk_when_consistent_and_well_sampled():
    result = assess_overfitting("strat_b", is_sharpe=1.0, oos_sharpe=0.9, n_trades=200, n_param_combos_tested=5)
    assert result.risk_level == "low"
    assert result.reasons == []


def test_deflated_sharpe_ratio_decreases_with_more_trials():
    dsr_few = deflated_sharpe_ratio(observed_sharpe=1.0, sharpe_std_across_trials=0.3, n_trials=2, n_obs=250)
    dsr_many = deflated_sharpe_ratio(observed_sharpe=1.0, sharpe_std_across_trials=0.3, n_trials=500, n_obs=250)
    assert dsr_many < dsr_few


def test_deflated_sharpe_ratio_bounded_0_1():
    dsr = deflated_sharpe_ratio(observed_sharpe=1.5, sharpe_std_across_trials=0.4, n_trials=100, n_obs=500)
    assert 0.0 <= dsr <= 1.0


def test_probability_of_backtest_overfitting_proxy():
    assert probability_of_backtest_overfitting_proxy([]) == 0.0
    assert probability_of_backtest_overfitting_proxy([1.0, 1.5, 2.0]) == 0.0
    assert probability_of_backtest_overfitting_proxy([-1.0, -0.5, 1.0, 2.0]) == 0.5
