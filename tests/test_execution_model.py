import pytest
from quant.execution_model import ExecutionModel

def test_execution_cost_reduces_net_alpha_and_filters():
    model=ExecutionModel(gamma=0.1,min_net_alpha=0.03)
    small=model.estimate(100_000,10_000_000,0.02,2,1,expected_alpha=0.05)
    large=model.estimate(2_000_000,10_000_000,0.02,2,1,expected_alpha=0.05)
    assert large.total_cost_bps>small.total_cost_bps
    assert large.net_expected_alpha<small.net_expected_alpha
    assert isinstance(small.accepted,bool)

def test_invalid_adv_rejected():
    with pytest.raises(ValueError):
        ExecutionModel().estimate(1000,0,0.02)
