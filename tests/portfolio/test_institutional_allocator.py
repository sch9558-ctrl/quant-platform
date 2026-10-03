import numpy as np
import pandas as pd

from quant.portfolio.constructor import PortfolioItem
from quant.portfolio.institutional import build_institutional_allocation


def _inputs(n=12):
    rng=np.random.default_rng(42)
    idx=pd.bdate_range("2025-01-01",periods=180)
    ohlcv={}
    items=[]
    caps={}
    edges={}
    for i in range(n):
        symbol=f"S{i:02d}"
        ret=rng.normal(0.0003+i*0.00001,0.01+i*0.0001,len(idx))
        close=100*np.exp(np.cumsum(ret))
        ohlcv[symbol]=pd.DataFrame({"close":close},index=idx)
        items.append(PortfolioItem(symbol,"korea","scanner",signal_strength=.7,volatility=.2))
        caps[symbol]=1_000_000_000_000*(i+1)
        edges[symbol]={"n_obs":20+i,"mean_fwd_return":0.01+i*0.0002,"win_rate":.55}
    return items,ohlcv,caps,edges


def test_institutional_allocator_uses_bl_with_real_market_caps_and_views():
    items,ohlcv,caps,edges=_inputs()
    allocation,diag=build_institutional_allocation(
        items,ohlcv,market_caps=caps,signal_edges=edges
    )
    assert allocation is not None
    assert diag is not None
    assert diag.method=="black_litterman"
    assert diag.prior_source=="market_cap"
    assert diag.view_count==len(items)
    assert allocation.weights.max()<=.10+1e-9
    assert allocation.by_market["korea"]<=.70+1e-9
    assert allocation.cash_weight>=.30-1e-9
    assert any("black_litterman" in note for note in allocation.notes)


def test_institutional_allocator_falls_back_to_hrp_without_market_caps():
    items,ohlcv,_,edges=_inputs(8)
    allocation,diag=build_institutional_allocation(
        items,ohlcv,market_caps={},signal_edges=edges
    )
    assert allocation is not None
    assert diag is not None
    assert diag.method=="hrp"
    assert diag.prior_source=="missing_market_cap"
    assert allocation.weights.max()<=.10+1e-9
    assert any("institutional allocator: hrp" in note for note in allocation.notes)


def test_institutional_allocator_returns_none_when_history_is_too_short():
    items,ohlcv,caps,edges=_inputs(4)
    short={k:v.tail(20) for k,v in ohlcv.items()}
    allocation,diag=build_institutional_allocation(
        items,short,market_caps=caps,signal_edges=edges
    )
    assert allocation is None
    assert diag is None
