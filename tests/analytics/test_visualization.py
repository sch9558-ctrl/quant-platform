import matplotlib
import numpy as np
import pandas as pd
import pytest

matplotlib.use("Agg")

from quant.analytics import visualization as viz


@pytest.fixture
def equity():
    idx = pd.bdate_range("2020-01-01", periods=500)
    rng = np.random.default_rng(0)
    return pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, 500))), index=idx)


@pytest.fixture
def daily_returns(equity):
    return equity.pct_change().fillna(0.0)


def test_plot_equity_curve(equity):
    fig = viz.plot_equity_curve(equity)
    assert fig is not None


def test_plot_drawdown(equity):
    fig = viz.plot_drawdown(equity)
    assert fig is not None


def test_plot_rolling_sharpe(daily_returns):
    fig = viz.plot_rolling_sharpe(daily_returns, window=60)
    assert fig is not None


def test_plot_monthly_returns_heatmap(daily_returns):
    fig = viz.plot_monthly_returns_heatmap(daily_returns)
    assert fig is not None


def test_plot_yearly_returns(daily_returns):
    fig = viz.plot_yearly_returns(daily_returns)
    assert fig is not None


def test_plot_strategy_comparison():
    df = pd.DataFrame({"strategy_id": ["A", "B", "C"], "sharpe": [1.2, 0.5, -0.3]})
    fig = viz.plot_strategy_comparison(df, metric="sharpe")
    assert fig is not None


def test_plot_correlation_matrix():
    idx = pd.bdate_range("2020-01-01", periods=100)
    rng = np.random.default_rng(1)
    returns = pd.DataFrame(rng.normal(0, 0.01, (100, 4)), index=idx, columns=["A", "B", "C", "D"])
    fig = viz.plot_correlation_matrix(returns)
    assert fig is not None


def test_plot_portfolio_allocation():
    fig = viz.plot_portfolio_allocation({"Cash": 0.2, "Korea": 0.3, "US": 0.5})
    assert fig is not None


def test_plot_candidate_ranking():
    df = pd.DataFrame({"symbol": [f"S{i}" for i in range(30)], "composite_score": np.random.default_rng(2).uniform(0, 1, 30)})
    fig = viz.plot_candidate_ranking(df, top_n=10)
    assert fig is not None


def test_save_figure(equity, tmp_path):
    fig = viz.plot_equity_curve(equity)
    out = tmp_path / "equity.png"
    viz.save_figure(fig, str(out))
    assert out.exists()
    assert out.stat().st_size > 0
