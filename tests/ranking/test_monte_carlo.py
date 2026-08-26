import numpy as np
import pandas as pd
import pytest

from quant.ranking.monte_carlo import run_monte_carlo


def test_positive_drift_series_has_low_risk_of_ruin():
    idx = pd.bdate_range("2020-01-01", periods=500)
    rng = np.random.default_rng(0)
    returns = pd.Series(rng.normal(0.0006, 0.008, 500), index=idx)
    result = run_monte_carlo(returns, n_simulations=500, seed=1)
    assert result.median_final_return > 0
    assert result.risk_of_ruin < 0.05


def test_highly_volatile_negative_drift_has_higher_ruin_risk():
    idx = pd.bdate_range("2020-01-01", periods=500)
    rng = np.random.default_rng(0)
    calm = pd.Series(rng.normal(0.0006, 0.008, 500), index=idx)
    risky = pd.Series(rng.normal(-0.002, 0.04, 500), index=idx)

    calm_result = run_monte_carlo(calm, n_simulations=500, seed=2)
    risky_result = run_monte_carlo(risky, n_simulations=500, seed=2)

    assert risky_result.risk_of_ruin >= calm_result.risk_of_ruin
    assert risky_result.median_final_return < calm_result.median_final_return


def test_percentile_ordering_is_sane():
    idx = pd.bdate_range("2020-01-01", periods=300)
    returns = pd.Series(np.random.default_rng(3).normal(0.0003, 0.015, 300), index=idx)
    result = run_monte_carlo(returns, n_simulations=1000, seed=4)
    assert result.worst_case_final_return <= result.median_final_return <= result.best_case_final_return
    assert result.drawdown_95th_percentile <= result.median_max_drawdown <= 0


def test_empty_returns_handled_gracefully():
    result = run_monte_carlo(pd.Series(dtype=float))
    assert result.n_simulations == 0
    assert result.median_final_return == 0.0


def test_horizon_can_exceed_history_length():
    idx = pd.bdate_range("2020-01-01", periods=60)
    returns = pd.Series(np.random.default_rng(5).normal(0.0003, 0.01, 60), index=idx)
    result = run_monte_carlo(returns, n_simulations=200, horizon=500, block_size=5, seed=6)
    assert result.horizon == 500
    assert len(result.final_return_distribution) == 200
