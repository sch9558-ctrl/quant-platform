"""Known-Answer Tests + Independent Verification (spec sections 55-59).

Every expected value in this file is derived BY HAND from the documented
formula/config -- never by calling the code under test and asserting it
equals itself. Small, fixed, hand-computable datasets (a 10-day price
series, a 5-value return series, a 7-day equity curve) with manually
worked-out expected results for: moving average, cumulative return,
drawdown + recovery, transaction cost, and Sharpe/Sortino.

The Sharpe/Sortino tests additionally serve as Independent Verification
(spec section 58): each computes the metric a second way -- via a
from-scratch numpy calculation written directly in this test file, not by
importing or reusing any part of quant.analytics.metrics's own formula --
and asserts the library's result agrees within a tight tolerance. The
project's own written cost formulas (per quant/backtest/costs.py's
docstring and config/costs.yaml) are treated as the independent
"reference calculation" for the transaction-cost tests, since those are
already a closed-form, hand-traceable formula rather than a second live
implementation.

Never trust an external library's or the codebase's own internal
consistency alone -- that is exactly the failure mode this file exists to
catch (spec: "외부 라이브러리 계산을 소규모 데이터셋으로 검증하지 않고
맹신하지 않는다").
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant.analytics.metrics import (
    cumulative_return, drawdown_series, max_drawdown, max_drawdown_recovery_days,
    sharpe_ratio, sortino_ratio,
)
from quant.backtest.costs import CostModel
from quant.features.trend import sma

TRADING_DAYS_PER_YEAR = 252


# ---------------------------------------------------------------------
# Moving Average (10-day fixed price series)
# ---------------------------------------------------------------------
def test_known_answer_sma_5day():
    # Hand-computed 5-day simple moving average over 10 close prices.
    # Day (1-indexed): 1    2    3    4    5    6    7    8    9    10
    prices_list = [100, 102, 101, 105, 107, 106, 110, 108, 112, 115]
    dates = pd.date_range("2024-01-02", periods=10, freq="B")
    prices = pd.Series(prices_list, index=dates)

    result = sma(prices, 5)

    # First 4 days: undefined (fewer than 5 observations) -- must be NaN,
    # never silently backfilled with a partial-window average (that would
    # be a subtle look-ahead/undercount bug).
    assert result.iloc[:4].isna().all()

    # Day 5: mean(100,102,101,105,107) = 515/5 = 103.0
    assert result.iloc[4] == pytest.approx(103.0)
    # Day 6: mean(102,101,105,107,106) = 521/5 = 104.2
    assert result.iloc[5] == pytest.approx(104.2)
    # Day 7: mean(101,105,107,106,110) = 529/5 = 105.8
    assert result.iloc[6] == pytest.approx(105.8)
    # Day 8: mean(105,107,106,110,108) = 536/5 = 107.2
    assert result.iloc[7] == pytest.approx(107.2)
    # Day 9: mean(107,106,110,108,112) = 543/5 = 108.6
    assert result.iloc[8] == pytest.approx(108.6)
    # Day 10: mean(106,110,108,112,115) = 551/5 = 110.2
    assert result.iloc[9] == pytest.approx(110.2)


# ---------------------------------------------------------------------
# Cumulative Return
# ---------------------------------------------------------------------
def test_known_answer_cumulative_return():
    # 100 -> 115 over the same 10-day series: (115/100) - 1 = 0.15 exactly.
    dates = pd.date_range("2024-01-02", periods=10, freq="B")
    equity = pd.Series([100, 102, 101, 105, 107, 106, 110, 108, 112, 115], index=dates)
    assert cumulative_return(equity) == pytest.approx(0.15)


# ---------------------------------------------------------------------
# Drawdown + Recovery (7-day fixed equity curve)
# ---------------------------------------------------------------------
def test_known_answer_drawdown_and_recovery():
    # Day:      1    2    3    4    5    6    7
    # Equity:  100  110  105  120   90   95  125
    # Running max: 100 110 110 120 120 120 125
    # Drawdown:      0%   0%  -4.5454...%  0%  -25%  -20.8333...%  0%
    dates = pd.date_range("2024-01-01", periods=7, freq="D")
    equity = pd.Series([100, 110, 105, 120, 90, 95, 125], index=dates)

    dd = drawdown_series(equity)
    assert dd.iloc[0] == pytest.approx(0.0)
    assert dd.iloc[1] == pytest.approx(0.0)
    assert dd.iloc[2] == pytest.approx(105 / 110 - 1)   # -0.045454...
    assert dd.iloc[3] == pytest.approx(0.0)
    assert dd.iloc[4] == pytest.approx(90 / 120 - 1)    # -0.25 exactly
    assert dd.iloc[5] == pytest.approx(95 / 120 - 1)    # -0.208333...
    assert dd.iloc[6] == pytest.approx(0.0)

    # Worst drawdown is exactly -25% (day 5, the trough of 90 against the
    # prior peak of 120 set on day 4).
    assert max_drawdown(equity) == pytest.approx(-0.25)

    # Recovery: trough is day 5 (value 90, prior peak 120 from day 4).
    # Equity first reaches >= 120 again on day 7 (125) -- 2 calendar days
    # after the trough.
    assert max_drawdown_recovery_days(equity) == 2


def test_known_answer_drawdown_never_recovers_within_window():
    # Same curve but truncated before the recovery day -- must return
    # None, never a fabricated or negative "days to recover".
    dates = pd.date_range("2024-01-01", periods=6, freq="D")
    equity = pd.Series([100, 110, 105, 120, 90, 95], index=dates)
    assert max_drawdown_recovery_days(equity) is None


# ---------------------------------------------------------------------
# Transaction Cost (hand-traced against config/costs.yaml's own documented
# rates: Korea commission 0.015%, KOSPI sell tax 0.18%, 5bp slippage;
# US commission-free, SEC fee 0.00278%, FINRA TAF $0.000166/share
# approximated via notional/$50, 5bp slippage.)
# ---------------------------------------------------------------------
def test_known_answer_korea_round_trip_transaction_cost():
    cost_model = CostModel("korea")

    # Buy 1,000,000 KRW notional of a KOSPI equity: commission-only (no
    # tax on buys), no tax, 5bp slippage.
    #   commission = 1,000,000 * 0.00015          = 150.0
    #   tax        = 0 (buy side)
    #   slippage   = 1,000,000 * 5 / 10,000        = 500.0
    #   total      = 650.0
    buy_fill = cost_model.apply(1_000_000, is_sell=False, asset_type="equity", exchange="KOSPI")
    assert buy_fill.commission == pytest.approx(150.0)
    assert buy_fill.tax_or_fee == pytest.approx(0.0)
    assert buy_fill.slippage_cost == pytest.approx(500.0)
    assert buy_fill.total_cost == pytest.approx(650.0)

    # Sell at 1,050,000 KRW notional (a +5% move on the position):
    #   commission = 1,050,000 * 0.00015           = 157.5
    #   tax        = 1,050,000 * 0.0018             = 1890.0
    #   slippage   = 1,050,000 * 5 / 10,000         = 525.0
    #   total      = 2572.5
    sell_fill = cost_model.apply(1_050_000, is_sell=True, asset_type="equity", exchange="KOSPI")
    assert sell_fill.commission == pytest.approx(157.5)
    assert sell_fill.tax_or_fee == pytest.approx(1890.0)
    assert sell_fill.slippage_cost == pytest.approx(525.0)
    assert sell_fill.total_cost == pytest.approx(2572.5)

    # Net PnL of the round trip: gross 50,000 minus 650.0 (buy) minus
    # 2572.5 (sell) = 46,777.5.
    gross_pnl = 1_050_000 - 1_000_000
    net_pnl = gross_pnl - buy_fill.total_cost - sell_fill.total_cost
    assert net_pnl == pytest.approx(46_777.5)


def test_known_answer_us_round_trip_transaction_cost():
    cost_model = CostModel("us")

    # Buy 100 shares @ $50 = $5,000 notional: commission-free, no fee on
    # buys, 5bp slippage.
    #   slippage = 5,000 * 5 / 10,000 = 2.5
    buy_fill = cost_model.apply(5_000, is_sell=False)
    assert buy_fill.commission == pytest.approx(0.0)
    assert buy_fill.tax_or_fee == pytest.approx(0.0)
    assert buy_fill.slippage_cost == pytest.approx(2.5)
    assert buy_fill.total_cost == pytest.approx(2.5)

    # Sell 100 shares @ $55 = $5,500 notional:
    #   SEC fee   = 5,500 * 0.0000278             = 0.1529
    #   FINRA TAF = (5,500 / 50) * 0.000166        = 0.01826  (approximated via assumed $50/share)
    #   fee total = 0.1529 + 0.01826               = 0.17116
    #   slippage  = 5,500 * 5 / 10,000              = 2.75
    #   total     = 2.92116
    sell_fill = cost_model.apply(5_500, is_sell=True)
    assert sell_fill.tax_or_fee == pytest.approx(0.17116, abs=1e-5)
    assert sell_fill.slippage_cost == pytest.approx(2.75)
    assert sell_fill.total_cost == pytest.approx(2.92116, abs=1e-5)

    # Net PnL: gross 500.0 minus 2.5 (buy) minus 2.92116 (sell) = 494.57884
    gross_pnl = 5_500 - 5_000
    net_pnl = gross_pnl - buy_fill.total_cost - sell_fill.total_cost
    assert net_pnl == pytest.approx(494.57884, abs=1e-4)


# ---------------------------------------------------------------------
# Sharpe / Sortino -- Independent Verification (spec section 58): computed
# a second, from-scratch way in this test file and cross-checked against
# quant.analytics.metrics's implementation.
# ---------------------------------------------------------------------
def test_independent_verification_sharpe_ratio():
    # Fixed 5-day daily return series (round numbers by design so the
    # by-hand arithmetic stays traceable):
    #   returns = [+1%, -1%, +2%, -2%, +1%]
    #   mean = 0.002, sample std (ddof=1) = sqrt(0.00108/4) = 0.01643167...
    #   annualized Sharpe = mean/std * sqrt(252) ~= 1.9322
    returns = pd.Series([0.01, -0.01, 0.02, -0.02, 0.01])

    lib_sharpe = sharpe_ratio(returns)

    # Independent implementation: plain numpy, no reuse of the library's
    # own excess/std/annualize code path.
    r = returns.to_numpy(dtype=float)
    mean = r.mean()
    std = r.std(ddof=1)
    manual_sharpe = mean / std * np.sqrt(TRADING_DAYS_PER_YEAR)

    assert lib_sharpe == pytest.approx(manual_sharpe, rel=1e-9)
    assert lib_sharpe == pytest.approx(1.932183566158592, rel=1e-9)  # hand/pre-verified constant


def test_independent_verification_sortino_ratio():
    returns = pd.Series([0.01, -0.01, 0.02, -0.02, 0.01])

    lib_sortino = sortino_ratio(returns)

    r = returns.to_numpy(dtype=float)
    mean = r.mean()
    downside = r[r < 0]
    downside_std = downside.std(ddof=1)
    manual_sortino = mean / downside_std * np.sqrt(TRADING_DAYS_PER_YEAR)

    assert lib_sortino == pytest.approx(manual_sortino, rel=1e-9)
    assert lib_sortino == pytest.approx(4.48998886412873, rel=1e-9)  # hand/pre-verified constant


def test_independent_verification_sharpe_zero_variance_returns_zero_not_nan():
    # A degenerate all-identical-returns series has zero variance --
    # dividing by zero would produce inf/NaN, which must never leak into
    # a report as a valid-looking Sharpe. The library defines this as 0.0;
    # verify that contract explicitly rather than assuming.
    flat_returns = pd.Series([0.01, 0.01, 0.01, 0.01, 0.01])
    assert sharpe_ratio(flat_returns) == 0.0
    assert not np.isnan(sharpe_ratio(flat_returns))
    assert not np.isinf(sharpe_ratio(flat_returns))
