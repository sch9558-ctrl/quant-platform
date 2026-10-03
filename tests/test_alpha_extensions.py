import numpy as np
import pandas as pd
from quant.analytics.consensus_acceleration import consensus_acceleration
from quant.analytics.pairs_trading import analyze_pair
from quant.analytics.regime_detector import hurst_regime
from quant.analytics.supply_chain import lagging_opportunities
from quant.macro.cross_asset import korea_macro_filter,us_macro_filter

def test_consensus_acceleration_and_macro_filters():
    dates=pd.date_range("2026-07-01",periods=90)
    values=np.concatenate([np.linspace(100,105,60),np.linspace(106,125,30)])
    out=consensus_acceleration(pd.DataFrame({"date":dates,"target_price":values}))
    assert out["velocity_30d"] is not None
    assert korea_macro_filter(.01,-.01).macro_risk_elevated
    assert us_macro_filter(30).block_high_beta_growth

def test_pair_and_hurst_and_supply_chain():
    rng=np.random.default_rng(4); x=np.cumsum(rng.normal(0,.01,150))+5
    a=np.exp(x); b=np.exp(x+rng.normal(0,.01,150))
    pair=analyze_pair(pd.Series(a),pd.Series(b),90)
    assert pair.pvalue<0.2
    regime=hurst_regime(pd.Series(np.exp(np.linspace(1,3,200)+rng.normal(0,.01,200))))
    assert 0<=regime["hurst"]<=1
    sig=lagging_opportunities("NVDA",.05,{"000660":.005,"042700":.001,"007660":.02})
    assert any(x.signal=="SUPPLY_CHAIN_LAGGING_OPPORTUNITY" for x in sig)
