import pytest

from quant.execution_model import ExecutionModel


def test_execution_cost_rises_with_participation():
    model=ExecutionModel(gamma=0.10)
    small=model.estimate_cost(order_notional=10_000,adv_notional=10_000_000,sigma=0.02,half_spread_bps=2,exchange_fee_bps=1)
    large=model.estimate_cost(order_notional=1_000_000,adv_notional=10_000_000,sigma=0.02,half_spread_bps=2,exchange_fee_bps=1)
    assert large.impact_bps > small.impact_bps
    assert small.total_one_way_bps == pytest.approx(small.impact_bps+3)


def test_net_alpha_filter_rejects_expensive_trade():
    model=ExecutionModel(gamma=0.2,min_net_alpha_pct=3.0)
    a=model.assess_signal(gross_alpha_pct=3.1,order_notional=2_000_000,adv_notional=5_000_000,sigma=0.04,half_spread_bps=8,exchange_fee_bps=2)
    assert not a.accepted
    b=model.assess_signal(gross_alpha_pct=8.0,order_notional=50_000,adv_notional=50_000_000,sigma=0.015,half_spread_bps=1,exchange_fee_bps=0.5)
    assert b.accepted
    assert b.net_alpha_pct < b.gross_alpha_pct
