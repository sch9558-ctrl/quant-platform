import numpy as np
import pandas as pd
import pytest
from quant.volatility_targeting import target_volatility

def test_volatility_targeting_scales_down_high_vol():
    rng=np.random.default_rng(11)
    r=pd.Series(rng.normal(0,0.24/np.sqrt(252),300))
    out=target_volatility(r,target_vol=0.12)
    assert 0<out.realized_vol
    assert 0<out.equity_weight<1
    assert out.cash_weight==pytest.approx(1-out.equity_weight)

def test_zero_vol_stays_fully_invested():
    out=target_volatility(pd.Series([0.0]*40))
    assert out.equity_weight==pytest.approx(1.0)
