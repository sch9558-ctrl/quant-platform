import numpy as np
import pandas as pd
import pytest

from quant.analytics import metrics as m


def _equity_from_returns(returns: list[float], start_value: float = 100.0) -> pd.Series:
    idx = pd.bdate_range("2020-01-01", periods=len(returns) + 1)
    values = [start_value]
    for r in returns:
        values.append(values[-1] * (1 + r))
    return pd.Series(values, index=idx)


def test_cagr_known_case():
    # exactly double in exactly 1 year -> CAGR should be ~100%
    idx = pd.DatetimeIndex(["2020-01-01", "2021-01-01"])
    equity = pd.Series([100.0, 200.0], index=idx)
    assert m.cagr(equity) == pytest.approx(1.0, rel=1e-2)


def test_max_drawdown_known_case():
    equity = pd.Series([100, 120, 90, 95, 130], index=pd.bdate_range("2020-01-01", periods=5))
    dd = m.max_drawdown(equity)
    assert dd == pytest.approx(90 / 120 - 1)


def test_max_drawdown_recovery_days():
    idx = pd.bdate_range("2020-01-01", periods=6)
    equity = pd.Series([100, 120, 90, 95, 121, 130], index=idx)
    recovery = m.max_drawdown_recovery_days(equity)
    assert recovery is not None
    assert recovery >= 0


def test_max_drawdown_recovery_none_if_unrecovered():
    idx = pd.bdate_range("2020-01-01", periods=4)
    equity = pd.Series([100, 120, 90, 95], index=idx)
    assert m.max_drawdown_recovery_days(equity) is None


def test_sharpe_zero_for_constant_returns():
    idx = pd.bdate_range("2020-01-01", periods=50)
    returns = pd.Series(0.001, index=idx)  # zero std -> sharpe defined as 0 by our guard
    assert m.sharpe_ratio(returns) == 0.0


def test_sharpe_positive_for_positive_drift():
    idx = pd.bdate_range("2020-01-01", periods=252)
    rng = np.random.default_rng(0)
    returns = pd.Series(rng.normal(0.001, 0.01, 252), index=idx)
    assert m.sharpe_ratio(returns) > 0


def test_sortino_ignores_upside_volatility():
    idx = pd.bdate_range("2020-01-01", periods=100)
    # returns alternate between a big positive leg (with some noise, so the
    # *upside* has real dispersion) and a small, fairly stable negative leg
    # -- lots of total vol, but only the (low-dispersion) downside leg
    # should count against sortino, so sortino should end up higher than
    # sharpe. A perfectly constant downside leg would make downside std
    # exactly 0, an edge case our formula deliberately treats as "sortino
    # undefined -> 0" (see sortino_ratio's guard) rather than infinite, so
    # a touch of noise keeps this test in the realistic regime.
    rng = np.random.default_rng(3)
    returns = pd.Series(
        [0.05 + rng.normal(0, 0.02) if i % 2 == 0 else -0.001 + rng.normal(0, 0.0002) for i in range(100)],
        index=idx,
    )
    sharpe = m.sharpe_ratio(returns)
    sortino = m.sortino_ratio(returns)
    assert sortino > sharpe


def test_calmar_ratio():
    assert m.calmar_ratio(0.20, -0.10) == pytest.approx(2.0)
    assert m.calmar_ratio(0.20, 0.0) == 0.0


def test_alpha_beta_recovers_known_linear_relationship():
    idx = pd.bdate_range("2020-01-01", periods=500)
    rng = np.random.default_rng(1)
    bench = pd.Series(rng.normal(0.0003, 0.01, 500), index=idx)
    noise = rng.normal(0, 0.001, 500)
    strat = 1.5 * bench + 0.0002 + noise  # beta=1.5, small positive daily alpha
    alpha_ann, beta = m.alpha_beta(strat, bench)
    assert beta == pytest.approx(1.5, abs=0.15)
    assert alpha_ann == pytest.approx(0.0002 * 252, abs=0.03)


def test_information_ratio_zero_when_tracking_exactly():
    idx = pd.bdate_range("2020-01-01", periods=100)
    bench = pd.Series(np.random.default_rng(2).normal(0, 0.01, 100), index=idx)
    assert m.information_ratio(bench, bench) == 0.0


def test_reconstruct_round_trip_trades_basic():
    idx = pd.bdate_range("2020-01-01", periods=10)
    weights = pd.DataFrame({"A": [0, 1, 1, 1, 0, 0, 1, 1, 0, 0]}, index=idx, dtype=float)
    close = pd.Series(np.linspace(100, 109, 10), index=idx)
    ohlcv_map = {"A": pd.DataFrame({"adj_close": close})}

    trades = m.reconstruct_round_trip_trades(weights, ohlcv_map)
    assert len(trades) == 2
    assert trades[0].symbol == "A"
    assert trades[0].entry_date == idx[1]
    assert trades[0].exit_date == idx[3]


def test_trade_statistics_win_rate_and_profit_factor():
    trades = [
        m.RoundTripTrade("A", pd.Timestamp("2020-01-01"), pd.Timestamp("2020-01-05"), 5, 0.10),
        m.RoundTripTrade("A", pd.Timestamp("2020-02-01"), pd.Timestamp("2020-02-05"), 5, -0.05),
        m.RoundTripTrade("B", pd.Timestamp("2020-03-01"), pd.Timestamp("2020-03-10"), 10, 0.20),
    ]
    stats = m.trade_statistics(trades)
    assert stats["num_trades"] == 3
    assert stats["win_rate"] == pytest.approx(2 / 3)
    assert stats["profit_factor"] == pytest.approx((0.10 + 0.20) / 0.05)
    assert stats["avg_holding_period_days"] == pytest.approx((5 + 5 + 10) / 3)


def test_compute_metrics_empty_equity_returns_zeros():
    result = m.compute_metrics(pd.Series(dtype=float), pd.Series(dtype=float))
    assert result.total_return == 0.0
    assert result.num_trades == 0
